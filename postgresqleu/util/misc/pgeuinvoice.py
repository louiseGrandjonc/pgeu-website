#!/usr/bin/env python
# -*- coding: utf-8 -*-

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus.tables import Table, TableStyle
from reportlab.platypus.flowables import Image
import cStringIO as StringIO

class PDFInvoice(object):
	def __init__(self, recipient, invoicedate, duedate, invoicenum=None, imagedir=None, currency='€', preview=False, receipt=False, bankinfo=True):
		self.pdfdata = StringIO.StringIO()
		self.canvas = Canvas(self.pdfdata)
		self.recipient = recipient
		self.invoicenum = invoicenum
		self.invoicedate = invoicedate
		self.duedate = duedate
		self.imagedir = imagedir or '.'
		self.currency = currency or '€'
		self.preview = preview
		self.receipt = receipt
		self.bankinfo = bankinfo
		self.rows = []

		if self.receipt:
			# Never include bank info on receipts
			self.bankinfo = False

		self.canvas.setTitle("PostgreSQL Europe Invoice #%s" % self.invoicenum)
		self.canvas.setSubject("PostgreSQL Europe Invoice #%s" % self.invoicenum)
		self.canvas.setAuthor("PostgreSQL Europe")
		self.canvas._doc.info.producer = "PostgreSQL Europe Invoicing System"

	def addrow(self, title, cost, count=1):
		self.rows.append((title, cost, count,))


	def trimstring(self, s, maxlen, fontname, fontsize):
		while len(s) > 5:
			if self.canvas.stringWidth(s, fontname, fontsize) <= maxlen:
				return s
			s = s[:len(s)-2]
		return s

	def _pageheader(self):
		if self.preview:
			t = self.canvas.beginText()
			t.setTextOrigin(6*cm, 4*cm)
			t.setFont("Times-Italic", 70)
			t.setFillColorRGB(0.9,0.9,0.9)
			t.textLines("PREVIEW PREVIEW")
			self.canvas.rotate(45)
			self.canvas.drawText(t)
			self.canvas.rotate(-45)

		im = Image("%s/PostgreSQL_logo.1color_blue.300x300.png" % self.imagedir, width=3*cm, height=3*cm)
		im.drawOn(self.canvas, 2*cm, 25*cm)
		t = self.canvas.beginText()
		t.setFillColorRGB(0,0,0,0)
		t.setFont("Times-Roman", 10)
		t.setTextOrigin(6*cm, 27.5*cm)
		t.textLines("""PostgreSQL Europe
Carpeaux Diem
13, rue du Square Carpeaux
75018 PARIS
France
""")
		self.canvas.drawText(t)

		t = self.canvas.beginText()
		t.setTextOrigin(2*cm, 23*cm)
		t.setFont("Times-Roman", 10)
		t.textLine("")
		t.textLines("""
Your contact: Guillaume Lelarge
Function: PostgreSQL Europe Treasurer
E-mail: treasurer@postgresql.eu
""")
		self.canvas.drawText(t)

		t = self.canvas.beginText()
		t.setTextOrigin(11*cm, 23*cm)
		t.setFont("Times-Italic", 11)
		t.textLine("To:")
		t.setFont("Times-Roman", 11)
		t.textLines(self.recipient)
		self.canvas.drawText(t)

		p = self.canvas.beginPath()
		p.moveTo(2*cm, 18.9*cm)
		p.lineTo(19*cm, 18.9*cm)
		self.canvas.drawPath(p)


	def save(self):
		# We can fit 15 rows on one page. We might want to do something
		# cute to avoid a single row on it's own page in the future, but
		# for now, just split it evenly.
		for pagenum in range(0, (len(self.rows)-1)/15+1):
			self._pageheader()
			islastpage = (pagenum == (len(self.rows)-1)/15)

			if len(self.rows) > 15:
				suffix = " (page %s/%s)" % (pagenum+1, len(self.rows)/15+1)
			else:
				suffix = ''

			# Center between 2 and 19 is 10.5
			if self.invoicenum:
				if self.receipt:
					self.canvas.drawCentredString(10.5*cm,19*cm, "RECEIPT FOR INVOICE NUMBER %s%s" % (self.invoicenum, suffix))
				else:
					self.canvas.drawCentredString(10.5*cm,19*cm, "INVOICE NUMBER %s - %s%s" % (self.invoicenum, self.invoicedate.strftime("%B %d, %Y"),suffix))
			else:
				self.canvas.drawCentredString(10.5*cm,19*cm, "RECEIPT - %s%s" % (self.invoicedate.strftime("%B %d, %Y"), suffix))

			if pagenum == 0:
				tbldata = [["Item", "Price", "Count", "Amount"], ]
			else:
				tbldata = [["Item - continued from page %s" % pagenum, "Price", "count", "amount"], ]

			tbldata.extend([(self.trimstring(title, 10.5*cm, "Times-Roman", 10),
							 "%.2f %s" % (cost, self.currency),
							 count,
							 "%.2f %s" % ((cost * count), self.currency))
							for title,cost, count in self.rows[pagenum*15:(pagenum+1)*15]])
			style = [
					('BACKGROUND',(0,0),(3,0),colors.lightgrey),
					('ALIGN',(1,0),(3,-1),'RIGHT'),
					('LINEBELOW',(0,0),(-1,0), 2, colors.black),
					('OUTLINE', (0,0), (-1, -1), 1, colors.black),
				]
			if islastpage:
				tbldata.append(['','','Total',"%.2f %s" % (sum([cost*count for title,cost,count in self.rows]),self.currency)])
				style.append(('LINEABOVE', (-2,-1), (-1, -1), 2, colors.black))
			else:
				tbldata.append(['          Continued on page %s' % (pagenum + 2), '', '', ''])
				style.append(('ALIGN', (0, -1), (-1, -1), 'CENTER'))
				style.append(('FONT', (0, -1), (-1, -1), 'Times-Italic'))

			t = Table(tbldata, [10.5*cm, 2.5*cm, 1.5*cm, 2.5*cm])
			t.setStyle(TableStyle(style))
			w,h = t.wrapOn(self.canvas,10*cm,10*cm)
			t.drawOn(self.canvas, 2*cm, 18*cm-h)

			if self.receipt:
				self.canvas.drawCentredString(10.5*cm,17.3*cm-h, "This invoice was paid %s" % self.duedate.strftime("%B %d, %Y"))
			else:
				self.canvas.drawCentredString(10.5*cm,17.3*cm-h, "This invoice is due: %s" % self.duedate.strftime("%B %d, %Y"))


			t = self.canvas.beginText()
			t.setTextOrigin(2*cm, 5*cm)
			t.setFont("Times-Italic", 10)
			t.textLine("PostgreSQL Europe is a French non-profit under the French 1901 Law. The association is not VAT registered.")
			t.textLine("")

			if islastpage and self.bankinfo:
				t.setFont("Times-Bold", 10)
				t.textLine("Bank references / Références bancaires / Bankverbindungen / Referencias bancarias")

				t.setFont("Times-Roman", 8)
				t.textLines("""CCM PARIS 1-2 LOUVRE MONTORGUEIL
28 RUE ETIENNE MARCEL
75002 PARIS
FRANCE
IBAN: FR76 1027 8060 3100 0205 2290 114
BIC: CMCIFR2A
""")

			self.canvas.drawText(t)

			# Finish this page off, and optionally loop to another one
			self.canvas.showPage()

		# Last page is finished, flush the PDF output
		self.canvas.save()

		return self.pdfdata
