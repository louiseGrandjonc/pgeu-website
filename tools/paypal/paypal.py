#!/usr/bin/env python
#
# This script downloads all paypal transaction data from one or more accounts,
# and stores them in the database for further processing. No attempt is made
# to match the payment to something elsewhere in the system - that is handled
# by separate scripts.
#
# Copyright (C) 2010, PostgreSQL Europe
#

from datetime import datetime, timedelta
import urllib2
from urllib import urlencode
from cgi import parse_qs
from decimal import Decimal
import sys
import psycopg2
import ConfigParser

class PaypalBaseTransaction(object):
	def __init__(self, paypalapi, apistruct, source, i):
		self.message = None
		self.api = paypalapi
		self.source = source

		self.transactionid = apistruct['L_TRANSACTIONID%i' % i][0]
		try:
			self.timestamp = datetime.strptime(apistruct['L_TIMESTAMP%i' % i][0], '%Y-%m-%dT%H:%M:%SZ')
			self.amount = Decimal(apistruct['L_AMT%i' % i][0])
			self.fee = -Decimal(apistruct['L_FEEAMT%i' % i][0])
			self.name = apistruct['L_NAME%i' % i][0]
		except Exception, e:
			self.message = "Unable to parse: %s" % e

	def __str__(self):
		if self.message:
			return self.message
		return "%s (%s): %s <%s> paid %s" % (
			self.transactionid,
			self.timestamp,
			self.name,
			self.email,
			self.amount,
		)

	def already_processed(self, db):
		cursor = db.cursor()
		cursor.execute("SELECT count(*) FROM paypal_transactioninfo WHERE paypaltransid=%(id)s", {
			'id': self.transactionid,
		})
		return (cursor.fetchall()[0][0] == 1)

	def fetch_details(self):
		r = self.api.get_transaction_details(self.transactionid)
		if r['TRANSACTIONTYPE'][0] == 'cart':
			# Always retrieve the first item in the cart
			# XXX: does this always come back in the same order as sent?
			# So far, all testing indicates it does
			self.text = r['L_NAME0'][0]
		elif r['TRANSACTIONTYPE'][0] == 'sendmoney':
			# This is sending of money, and not receiving. The transaction
			# text (naturally) goes in a completely different field.
			if r.has_key('NOTE'):
				self.text = 'Paypal payment: %s' % r['NOTE'][0]
			else:
				self.text = 'Paypal payment with empty note'
		else:
			if r.has_key('SUBJECT'):
				self.text = r['SUBJECT'][0]
			elif r.has_key('L_NAME0'):
				self.text = r['L_NAME0'][0]
			else:
				self.text = ""

		if r['L_CURRENCYCODE0'][0] != self.api.currency:
			self.message = "Invalid currency %s" % r['L_CURRENCYCODE0'][0]
			self.text += ' (currency %s, manually adjust amount!)' % r['L_CURRENCYCODE0'][0]
			self.amount = -1 # just to be on the safe side

	def store(self, db):
		cursor = db.cursor()
		cursor.execute("""
INSERT INTO paypal_transactioninfo
(paypaltransid, "timestamp", sourceaccount_id, sender, sendername, amount, fee, transtext, matched, matchinfo)
VALUES (%(id)s, %(ts)s, %(source)s, %(sender)s, %(name)s, %(amount)s, %(fee)s, %(text)s, %(matched)s, %(matchinfo)s)""", {
		'id': self.transactionid,
		'ts': self.timestamp,
		'source': self.source,
		'sender': self.email,
		'name': self.name,
		'amount': self.amount,
		'fee': self.fee,
		'text': self.text,
		'matched': False,
		'matchinfo': self.message,
	})

class PaypalTransaction(PaypalBaseTransaction):
	def __init__(self, paypalapi, apistruct, source, i):
		super(PaypalTransaction, self).__init__(paypalapi, apistruct, source, i)
		try:
			self.email = apistruct['L_EMAIL%i' % i][0]
		except Exception, e:
			self.message = "Unable to parse: %s" % e

class PaypalRefund(PaypalTransaction):
	def fetch_details(self):
		super(PaypalRefund, self).fetch_details()
		if self.text:
			self.text = "Refund of %s" % self.text
		else:
			self.text = "Refund of unknown transaction"

class PaypalTransfer(PaypalBaseTransaction):
	def __init__(self, paypalapi, apistruct, source, i):
		super(PaypalTransfer, self).__init__(paypalapi, apistruct, source, i)
		self.text = "Transfer from Paypal to bank"
		self.fee = 0
		self.email = 'treasurer@postgresql.eu'
		if apistruct['L_CURRENCYCODE%i' % i][0] != self.api.currency:
			self.message = "Invalid currency %s" % apistruct['L_CURRENCYCODE%i' % i][0]
			self.text += ' (currency %s, manually adjust amount!)' % r['L_CURRENCYCODE0'][0]
			self.amount = -1 # To be on the safe side

	def fetch_details(self):
		# We cannot fetch more details, but we also don't need more details..
		pass

class PaypalAPI(object):
	def __init__(self, apiuser, apipass, apisignature, sandbox, currency):
		if sandbox:
			self.API_ENDPOINT = 'https://api-3t.sandbox.paypal.com/nvp'
		else:
			self.API_ENDPOINT = 'https://api-3t.paypal.com/nvp'
		self.currency = currency
		self.apiuser = apiuser
		self.apipass = apipass
		self.apisignature = apisignature
		self.accessparam = {
			'USER': self.apiuser,
			'PWD': self.apipass,
			'SIGNATURE': self.apisignature,
			'VERSION': '56',
		}

	def get_transaction_list(self, firstdate, source):
		ret = self._api_call('TransactionSearch', {
			'STARTDATE': self._dateformat(firstdate),
			'STATUS': 'Success',
		})
		i = -1
		while True:
			i += 1
			if not ret.has_key('L_TRANSACTIONID%i' % i): break

			if ret['L_TYPE%i' % i][0] in ('Payment', 'Donation'):
				yield PaypalTransaction(self, ret, source, i)
			elif ret['L_TYPE%i' %i][0] in ('Transfer'):
				yield PaypalTransfer(self, ret, source, i)
			elif ret['L_TYPE%i' %i][0] in ('Refund'):
				yield PaypalRefund(self, ret, source, i)
			elif ret['L_TYPE%i' % i][0] in ('Fee Reversal'):
				# It seems these can be ignored since the actual fee info
				# is also present on the refund notice.
				pass
			elif ret['L_TYPE%i' % i][0] in ('Currency Conversion (credit)', 'Currency Conversion (debit)'):
				# A transfer in a different currency will generate the main transaction
				# as well as *two* extra, one debit and one credit, for the conversion itself.
				# We just care about the main transfer anyway, so we're just going to ignore
				# the currency exchange ones (details can always be checked on the paypal website
				# for things like exchange rates).
				pass
			elif ret['L_TYPE%i' % i][0] in ('Temporary Hold', 'Authorization'):
				# We can safely ignore temporary holds, as they are temporary.
				# We also ignore Authorization, because they will be reported
				# both as an authorization event and a payment event.
				pass
			else:
				print "Don't know what to do with paypal transaction of type %s" % ret['L_TYPE%i' % i][0]

	def get_transaction_details(self, transactionid):
		return self._api_call('GetTransactionDetails', {
			'TRANSACTIONID': transactionid,
		})

	def _dateformat(self, d):
		return d.strftime("%Y-%m-%dT%H:%M:%S")

	def _api_call(self, command, params):
		params.update(self.accessparam)
		params.update({
			'METHOD': command,
		})
		resp = urllib2.urlopen(self.API_ENDPOINT, urlencode(params)).read()
		return parse_qs(resp)


if __name__ == "__main__":
	if len(sys.argv) != 2:
		print "Usage: paypal.py <dsn>"
		sys.exit(1)

	db = psycopg2.connect(sys.argv[1])
	cursor = db.cursor()

	cfg = ConfigParser.ConfigParser()
	cfg.read('paypal.ini')

	synctime = datetime.now()

	for sect in cfg.sections():
		if not cfg.has_option(sect, 'sourceid'): continue
		if not cfg.has_option(sect, 'user'): continue
		if not cfg.has_option(sect, 'apipass'): continue
		if not cfg.has_option(sect, 'apisig'): continue

		sourceid = cfg.get(sect, 'sourceid')
		sandbox = 0
		if cfg.has_option(sect, 'sandbox'):
			if cfg.get(sect, 'sandbox') == "1":
				sandbox = 1

		s = PaypalAPI(cfg.get(sect, 'user'),
					  cfg.get(sect, 'apipass'),
					  cfg.get(sect, 'apisig'),
					  sandbox,
					  cfg.get(sect, 'currency'))
		cursor.execute("SELECT lastsync FROM paypal_sourceaccount WHERE id=%(id)s", {
			'id': sourceid,
		})
		for r in s.get_transaction_list(cursor.fetchall()[0][0]-timedelta(days=3), sourceid): #always sync with a little overlap
			if r.already_processed(db): continue
			r.fetch_details()
			r.store(db)
		cursor = db.cursor()
		cursor.execute("UPDATE paypal_sourceaccount SET lastsync=%(st)s WHERE id=%(id)s", {
			'st': synctime,
			'id': sourceid,
		})
		db.commit()
