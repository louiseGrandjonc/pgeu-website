from django.db.models import Q
from django.http import HttpResponse
from django import forms

from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Paragraph
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet

from postgresqleu.countries.models import Country
from models import ConferenceRegistration, RegistrationType, ConferenceAdditionalOption, ShirtSize

# Fields that are available in an advanced attendee report
attendee_report_fields = [
		('lastname', 'Last name', True, None),
		('firstname', 'First name', True, None),
		('email', 'E-mail', True, None),
		('company', 'Company', False, None),
		('address', 'Address', False, None),
		('country', 'Country', False, None),
		('phone', 'Phone', False, None),
		('twittername', 'Twitter', False, None),
		('nick', 'Nickname', False, None),
		('dietary', 'Dietary needs', False, None),
		('shirtsize.shirtsize', 'T-Shirt size', False, 'shirtsize__shirtsize'),
		('regtype.regtype', 'Registration type', False, 'regtype__sortkey'),
		('additionaloptionlist', 'Additional options', False, 'id'),
]

_attendee_report_field_map = dict([(a,(b,c,d)) for a,b,c,d in attendee_report_fields])

class ReportFilter(object):
	def __init__(self, id, name, queryset=None, querysetcol=None, emptyasnull=True):
		self.id = id
		self.name = name
		self.queryset = queryset
		self.querysetcol = querysetcol
		self.emptyasnull = emptyasnull

	def build_Q(self, val):
		if self.queryset:
			# Our input is a list of IDs. Return registrations that has
			# *any* of the given id's. But we need to make sure that
			# django doesn't evaluate it as a subselect.
			return Q(**{"%s__id__in" % self.id: val})
		else:
			# Just make sure it exists
			if self.emptyasnull:
				return Q(**{"%s__isnull" % self.id:False, "%s__gt" % self.id: ''})
			else:
				return Q(**{"%s__isnull" % self.id:False})

	@property
	def html(self):
		return """<input type="checkbox" name="adv_%s_on">%s%s""" % (
			self.id,
			self.name,
			self._widgetstring(),
		)

	def _widgetstring(self):
		if self.queryset:
			querysetcol = self.querysetcol

			# Wrapper class that will return our custom column
			class MultipleChoiceWrapper(forms.ModelMultipleChoiceField):
				def label_from_instance(self, obj):
					if querysetcol:
						return getattr(obj, querysetcol)
					else:
						return super(MultipleChoiceWrapper, self).label_from_instance(obj)

			field = MultipleChoiceWrapper(queryset=self.queryset)
			return "<blockquote>%s</blockquote>" % (field.widget.render("adv_%s" % self.id, None), )
		else:
			return "<br/>"

def attendee_report_filters(conference):
	yield ReportFilter('regtype', 'Registration type', RegistrationType.objects.filter(conference=conference), 'regtype')
	yield ReportFilter('country', 'Country', Country.objects.all())
	yield ReportFilter('company', 'Company')
	yield ReportFilter('phone', 'Phone')
	yield ReportFilter('twittername', 'Twitter')
	yield ReportFilter('nick', 'Nickname')
	yield ReportFilter('dietary', 'Dietary needs')
	yield ReportFilter('payconfirmedat', 'Payment confirmed', emptyasnull=False)
	yield ReportFilter('additionaloptions', 'Additional options', ConferenceAdditionalOption.objects.filter(conference=conference), 'name')
	yield ReportFilter('shirtsize', 'T-Shirt size', ShirtSize.objects.all())


class ReportWriterBase(object):
	def __init__(self, title, borders):
		self.rows = []
		self.title = title
		self.borders = borders

	def set_headers(self, headers):
		self.headers = headers

	def add_row(self, row):
		self.rows.append(row)

class ReportWriterHtml(ReportWriterBase):
	def render(self):
		resp = HttpResponse()
		if self.title:
			resp.write("<h1>%s</h1>" % self.title)
		resp.write('<table border="%s" cellspacing="0" cellpadding="1"><tr><th>%s</th></tr>' % (self.borders and 1 or 0, "</th><th>".join(self.headers)))
		for r in self.rows:
			resp.write("<tr><td>%s</td></tr>\n" % "</td><td>".join(r))
		resp.write("</table>\n")

		return resp

class ReportWriterPdf(ReportWriterBase):
	def set_orientation(self, orientation):
		self.orientation = orientation

	def render(self):
		resp = HttpResponse(content_type='application/pdf')

		registerFont(TTFont('DejaVu Serif', "/usr/share/fonts/truetype/ttf-dejavu/DejaVuSerif.ttf"))
		pagesize = self.orientation=='portrait' and A4 or landscape(A4)
		doc = SimpleDocTemplate(resp, pagesize=pagesize)

		story = []

		story.append(Paragraph(self.title, getSampleStyleSheet()['title']))

		tbldata = [self.headers]
		tbldata.extend(self.rows)
		t = Table(tbldata, splitByRow=1, repeatRows=1)
		style = [
			("FONTNAME", (0, 0), (-1, -1), "DejaVu Serif"),
			]
		if self.borders:
			style.extend([
			('GRID', (0,0), (-1, -1), 1, colors.black),
			('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
			])
		t.setStyle(TableStyle(style))
		story.append(t)

		doc.build(story)

		return resp

def build_attendee_report(conference, POST):
	title = POST['title']
	format = POST['format']
	orientation = POST['orientation']
	borders = POST.has_key('border')
	fields = POST.getlist('fields')
	extracols = filter(None, map(lambda x: x.strip(), POST['additionalcols'].split(',')))

	# Build the filters
	q = Q(conference=conference)
	for f in attendee_report_filters(conference):
		if POST.has_key("adv_%s_on" % f.id):
			# This filter is checked
			q = q & f.build_Q(POST.getlist("adv_%s" % f.id, None))

	# Figure out our order by
	orderby = map(lambda x: _attendee_report_field_map[x][2] and _attendee_report_field_map[x][2] or x, [POST['orderby1'],POST['orderby2']])

	# Run the query!
	result = ConferenceRegistration.objects.select_related('shirtsize', 'regtype', 'country', 'conference').filter(q).distinct().order_by(*orderby)

	if format=='html':
		writer = ReportWriterHtml(title, borders)
	elif format=='pdf':
		writer = ReportWriterPdf(title, borders)
		writer.set_orientation(orientation)
	else:
		raise Exception("Unknown format")

	allheaders = [_attendee_report_field_map[f][0] for f in fields]
	if len(extracols):
		allheaders.extend(extracols)
	writer.set_headers(allheaders)

	for r in result:
		row = []
		for f in fields:
			# Recursively step into other models if necessary
			o = [r]
			o.extend(f.split('.'))
			try:
				row.append(unicode(reduce(getattr, o)))
			except AttributeError:
				# NULL in a field, typically
				row.append('')
		if extracols:
			for x in extracols:
				row.append('')
		writer.add_row(row)

	return writer.render()