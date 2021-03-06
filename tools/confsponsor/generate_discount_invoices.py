#!/usr/bin/env python
#
#
# Generate invoices for discount codes. That is, sponsors that have ordered discount codes,
# that have now either expired or been used fully.
#

import os
import sys
from datetime import date, datetime, timedelta

# Set up to run in django environment
from django.core.management import setup_environ
sys.path.append(os.path.join(os.path.abspath(os.path.dirname(sys.argv[0])), '../../postgresqleu'))
import settings
setup_environ(settings)

from django.db import transaction, connection
from django.db.models import Q, F, Count
from django.template import Context
from django.template.loader import get_template

from postgresqleu.confreg.models import DiscountCode
from postgresqleu.confsponsor.models import Sponsor # Required for text based resolving in DiscountCode
from postgresqleu.mailqueue.util import send_simple_mail
from postgresqleu.invoices.util import InvoiceManager, InvoiceWrapper

if __name__ == "__main__":
	# We're always going to process all conferences, since most will not have any
	# open discount codes.

	with transaction.commit_on_success():
		filt = Q(sponsor__isnull=False, is_invoiced=False) & (Q(validuntil__lt=date.today()) | Q(num_uses__gte=F('maxuses')))
		codes = DiscountCode.objects.annotate(num_uses=Count('registrations')).filter(filt)
		for code in codes:
			# Either the code has expired, or it is fully used by now. Time to generate the invoice. We'll also
			# send an email to the sponsor (and the admins) to inform them of what's happening.
			# The invoice will be a one-off one, we don't need a registered manager for it since the
			# discounts have already been given out.

			if code.count == 0:
				# In case there is not a single user, we just notify the user of this and set it to
				# invoiced in the system so we don't try again.
				code.is_invoiced=True
				code.save()
				send_simple_mail(code.conference.sponsoraddr,
								 code.conference.sponsoraddr,
								 u"[{0}] Discount code expired".format(code.conference),
								 u"Discount code {0} has expired without any uses.".format(code.code))
				msg = get_template('confsponsor/mail/discount_expired.txt').render(Context({
					'code': code,
					'sponsor': code.sponsor,
					'conference': code.conference,
					'SITEBASE': settings.SITEBASE_SSL,
				}))
				for manager in code.sponsor.managers.all():
					send_simple_mail(code.conference.sponsoraddr,
									 manager.email,
									 u"[{0}] Discount code {1} expired".format(code.conference, code.code),
									 msg,
									 sendername=code.conference.conferencename,
									 receivername=u'{0} {1}'.format(manager.first_name, manager.last_name))
			else:
				# At least one use, so we generate the invoice
				invoicerows = []
				for r in code.registrations.all():
					if code.discountamount:
						# Fixed amount discount. Always apply
						discountvalue = code.discountamount
					else:
						# Percentage discount, so we need to calculate it. Ordered discount codes will
						# only support a registration-only style discount code, so only count it
						# against that.
						discountvalue = r.regtype.cost * code.discountpercentage/100
					invoicerows.append(['Attendee "{0}"'.format(r.fullname), 1, discountvalue])
				# All invoices are always due immediately
				manager = InvoiceManager()
				code.invoice = manager.create_invoice(
					code.sponsor_rep,
					code.sponsor_rep.email,
					u"{0} {1}".format(code.sponsor_rep.first_name, code.sponsor_rep.last_name),
					'%s\n%s' % (code.sponsor.name, code.sponsor.invoiceaddr),
					u'{0} discount code {1}'.format(code.conference, code.code),
					datetime.now(),
					date.today()+timedelta(days=1),
					invoicerows,
					bankinfo=True,
					accounting_account = settings.ACCOUNTING_CONFREG_ACCOUNT,
					accounting_object = code.conference.accounting_object,
					autopaymentoptions=True,
				)
				code.invoice.save()
				code.is_invoiced = True
				code.save()

				wrapper = InvoiceWrapper(code.invoice)
				wrapper.email_invoice()

				# Now also fire off emails, both to the admins and to all the managers of the sponsor
				# (so they know where the invoice was sent).
				send_simple_mail(code.conference.sponsoraddr,
								 code.conference.sponsoraddr,
								 u"[{0}] Discount code {1} has been invoiced".format(code.conference, code.code),
								 u"The discount code {0} has been closed,\nand an invoice has been sent to {1}.\n\nA total of {2} registrations used this code, and the total amount was {3}.\n".format(
									 code.code,
									 code.sponsor,
									 len(invoicerows),
									 code.invoice.total_amount,
								 ))
				msg = get_template('confsponsor/mail/discount_invoiced.txt').render(Context({
					'code': code,
					'conference': code.conference,
					'sponsor': code.sponsor,
					'invoice': code.invoice,
					'curr': settings.CURRENCY_ABBREV,
					'expired_time': code.validuntil < date.today(),
					'SITEBASE': settings.SITEBASE_SSL,
				}))
				for manager in code.sponsor.managers.all():
					send_simple_mail(code.conference.sponsoraddr,
									 manager.email,
									 u"[{0}] Discount code {1} has been invoiced".format(code.conference, code.code),
									 msg,
									 sendername=code.conference.conferencename,
									 receivername=u'{0} {1}'.format(manager.first_name, manager.last_name))
	connection.close()
