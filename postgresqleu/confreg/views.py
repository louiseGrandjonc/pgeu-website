from django.shortcuts import render_to_response, get_object_or_404
from django.http import HttpResponseRedirect, HttpResponse
from django.template import RequestContext
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings

from models import *
from forms import *

from datetime import datetime

@login_required
def home(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	conference = get_object_or_404(Conference, urlname=confname)

	if not conference.active:
		return render_to_response('confreg/closed.html', {
			'conference': conference,
		})

	try:
		reg = ConferenceRegistration.objects.get(conference=conference,
			attendee=request.user)
	except:
		# No previous regisration, grab some data from the user profile
		reg = ConferenceRegistration(conference=conference, attendee=request.user)
		reg.email = request.user.email
		namepieces = request.user.first_name.rsplit(None,2)
		if len(namepieces) == 2:
			reg.firstname = namepieces[0]
			reg.lastname = namepieces[1]
		else:
			reg.firstname = request.user.first_name

	if request.method == 'POST':
		form = ConferenceRegistrationForm(data=request.POST, instance=reg)
		if form.is_valid():
			reg = form.save(commit=False)
			reg.conference = conference
			reg.attendee = request.user
			reg.save()
	else:
		# This is just a get, so render the form
		form = ConferenceRegistrationForm(instance=reg)

	return render_to_response('confreg/regform.html', {
		'form': form,
		'reg': reg,
		'conference': conference,
		'costamount': reg.regtype and reg.regtype.cost or 0,
	}, context_instance=RequestContext(request))

@login_required
def feedback(request, confname):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	conference = get_object_or_404(Conference, urlname=confname)

	# Figure out if the user is registered
	try:
		r = ConferenceRegistration.objects.get(conference=conference, attendee=request.user)
	except ConferenceRegistration.NotFound, e:
		return HttpResponse('You are not registered for this conference.')

	if not r.payconfirmedat:
		return HttpResponse('You are not a confirmed attendee of this conference.')

	# Generate a list of all feedback:able sessions, meaning all sessions that have already started,
	# since you can't give feedback on something that does not yet exist.
	sessions = ConferenceSession.objects.select_related().filter(conference=conference).filter(starttime__lte=datetime.now())
	# Then get a list of everything this user has feedbacked on
	feedback = ConferenceSessionFeedback.objects.filter(conference=conference, attendee=request.user)

	# Since we can't trick django to do a LEFT JOIN for us here, implement that part
	# in code here. The number of sessions is always going to be low, so it won't
	# be too big a performance issue.
	for s in sessions:
		fb = [f for f in feedback if f.session==s]
		if len(fb):
			s.has_feedback = True

	return render_to_response('confreg/feedback_index.html', {
		'sessions': sessions,
		'conference': conference,
	}, context_instance=RequestContext(request))

@login_required
def feedback_session(request, confname, sessionid):
	if settings.FORCE_SECURE_FORMS and not request.is_secure():
		return HttpResponseRedirect(request.build_absolute_uri().replace('http://','https://',1))
	# Room for optimization: don't get these as separate steps
	conference = get_object_or_404(Conference, urlname=confname)
	session = get_object_or_404(ConferenceSession, pk=sessionid, conference=conference)

	try:
		feedback = ConferenceSessionFeedback.objects.get(conference=conference, session=session, attendee=request.user)
	except ConferenceSessionFeedback.DoesNotExist, e:
		feedback = ConferenceSessionFeedback()

	if request.method=='POST':
		form = ConferenceSessionFeedbackForm(data=request.POST, instance=feedback)
		if form.is_valid():
			feedback = form.save(commit=False)
			feedback.conference = conference
			feedback.attendee = request.user
			feedback.session = session
			feedback.save()
			return HttpResponseRedirect('..')
	else:
		form = ConferenceSessionFeedbackForm(instance=feedback)

	return render_to_response('confreg/feedback.html', {
		'session': session,
		'form': form,
		'conference': conference,
	}, context_instance=RequestContext(request))
