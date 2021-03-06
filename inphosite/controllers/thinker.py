import logging
import re

from pylons import request, response, session, tmpl_context as c
from pylons.controllers.util import abort, redirect
from pylons.decorators import validate
from pylons.decorators.cache import beaker_cache

from inphosite.controllers.entity import EntityController
from inphosite.lib.base import BaseController, render
import inphosite.lib.helpers as h
from inphosite.lib.rest import restrict, dispatch_on
from inpho.model.thinker import *
from inpho.model import Session
from inpho.model import Idea, Entity, User

from sqlalchemy import or_
from sqlalchemy.sql.expression import func

import sys
reload(sys)
sys.setdefaultencoding("utf-8")

log = logging.getLogger(__name__)

unary_vars = {
    'nationality' : {'object' : Nationality, 
                     'property' : 'nationalities'},
    'profession' : {'object' : Profession, 
                    'property' : 'professions'}
}
binary_vars = {
    'influenced' : {'object' : ThinkerInfluencedEvaluation, 
                        'reverse' : False, 'maxdegree' : 4},
    'influenced_by' : {'object' : ThinkerInfluencedEvaluation, 
                       'reverse' : True, 'maxdegree' : 4},
    'teacher_of' : {'object' : ThinkerTeacherEvaluation, 
                        'reverse' : False, 'maxdegree' : 1},
    'student_of' : {'object' : ThinkerTeacherEvaluation, 
                        'reverse' : True, 'maxdegree' : 1}
}

class ThinkerController(EntityController):
    _type = Thinker
    _controller = 'thinker'

    def graph(self, id, filetype='html', limit=False):
        sep_filter = request.params.get('sep_filter', False) 
        c.sep_filter = sep_filter

        c.thinker = h.fetch_obj(Thinker, id, new_id=True)
        return render('thinker/graph.%s' % filetype)
    
    def data_integrity(self, filetype='html', redirect=False):
        if not h.auth.is_logged_in():
            abort(401)
        if not h.auth.is_admin():
            abort(403)

        thinker_q = Session.query(Thinker)
        c.thinkers = list(thinker_q)

        c.missing_birth = []
        c.missing_death = []
        c.impossible_dates = []
        c.bad_teacher = []
        c.missing_sep_dir = []
        c.no_wiki = []
        c.bad_wiki = []

        for thinker in c.thinkers:
            # variable to pass over impossible teacher-student
            # relationship check. 
            pass_teacher_check = False
            
            # Missing birth dates
            if not getattr(thinker, 'birth_dates'):
                pass_teacher_check = True
                c.missing_birth.append(thinker)
            
            # Missing death dates
            if not getattr(thinker, 'death_dates'):
                pass_teacher_check = True
                c.missing_death.append(thinker)
            
            # Impossible date combinations
            if len(thinker.birth_dates) != 0 and len(thinker.death_dates) != 0:
                dob = thinker.birth_dates[0]        
                dod = thinker.death_dates[0]
                if dob.year > dod.year or (dod.year - dob.year) > 120:
                    pass_teacher_check = True
                    c.impossible_dates.append(thinker)
        
            # Impossible Teacher relationship
            # currently only set up to query teacher info.
            # Only runs if pass_teacher_check is False
            # Builds a list of tuples containing the thinker and
            # teacher that is incorrect.
            if not pass_teacher_check:
                thinker_birth = thinker.birth_dates[0]
                thinker_death = thinker.death_dates[0]
                teachers = thinker.teachers
                for teacher in teachers:
                    if getattr(teacher, 'birth_dates') and getattr(teacher, 'death_dates'):
                        teacher_birth = teacher.birth_dates[0]
                        teacher_death = teacher.death_dates[0]
                        if thinker_birth.year > teacher_death.year or thinker_death.year < teacher_birth.year:
                            c.bad_teacher.append((thinker, teacher))

            # Missing sep_dir
            if not getattr(thinker, 'sep_dir'):
                c.missing_sep_dir.append(thinker)

            # No Wiki page
            if not getattr(thinker, 'wiki'):
                c.no_wiki.append(thinker)

            # Bad Wiki format
            elif len(thinker.wiki) > 29:
                if thinker.wiki[:29] == "http://en.wikipedia.org/wiki/":
                    c.bad_wiki.append(thinker)
        # Duplicates
        # It is set up for pairs. If there is more than 2 of the same thinker it will have multiples
        c.duplicate = []
        c.sorted_thinkers = sorted(c.thinkers, key=lambda thinker: thinker.label)
        for i in range(len(c.sorted_thinkers) - 1):
            if c.sorted_thinkers[i].label == c.sorted_thinkers[i+1].label:
                c.duplicate.append(c.sorted_thinkers[i])
                c.duplicate.append(c.sorted_thinkers[i+1]) 


        return render('thinker/data_integrity.%s' % filetype)


    def _list_property(self, property, id, filetype='html', limit=False,
    sep_filter=False, type='thinker'):
        c.thinker = h.fetch_obj(Thinker, id)
         
        limit = int(request.params.get('limit', limit))
        start = int(request.params.get('start', 0))
        sep_filter = request.params.get('sep_filter', sep_filter)
        property = getattr(c.thinker, property)
        if sep_filter:
            property = property.filter(Entity.sep_dir != '')
        
        try:
            c.total = property.count()
        except TypeError:
            c.total = len(property)

        if limit:
            property = property[start:start+limit]
        
        c.entities = property
        return render('%s/%s-list.%s' %(type, type, filetype))

    def hyponyms(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('hyponyms', id, filetype, limit, sep_filter)

    def related(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('related', id, filetype, limit, sep_filter)
    
    def influenced(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('influenced', id, filetype, limit, sep_filter)
    
    def influenced_by(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('influenced_by', id, filetype, limit, sep_filter)
    
    def students(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('students', id, filetype, limit, sep_filter)
    
    def teachers(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('teachers', id, filetype, limit, sep_filter)

    def related_ideas(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('related_ideas', id, filetype, limit, sep_filter)

    def occurrences(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('occurrences', id, filetype, limit, sep_filter)
    
    def idea_occurrences(self, id=None, filetype='html', limit=20, sep_filter=False):
        return self._list_property('idea_occurrences', id, filetype, limit, sep_filter)



    # update teacher_of
    @restrict('POST')
    def teacher_of(self, id=None, id2=None, degree=1):
        if not h.auth.is_logged_in():
            abort(401)
       

        # TODO: verify that this keeps bad teacher-student relationships from happening
        teacher = fetch_obj(Thinker, id)
        student = fetch_obj(Thinker, id2)
        
        pass_teacher_check = False

        # Missing birth dates
        if not getattr(student, 'birth_dates'):
            pass_teacher_check = True
        
        # Missing death dates
        if not getattr(student, 'death_dates'):
            pass_teacher_check = True
        
        if pass_teacher_check != True:
            student_birth = student.birth_dates[0]
            student_death = student.death_dates[0]
            if getattr(teacher, 'birth_dates') and getattr(teacher, 'death_dates'):
                teacher_birth = teacher.birth_dates[0]
                teacher_death = teacher.death_dates[0]
                if student_birth.year > teacher_death.year or student_death.year < teacher_birth.year:
                    abort(400)
                
        return _thinker_evaluate(ThinkerTeacherEvaluation, id, id2, degree)


    # render the editing GUI
    def edit(self, id=None):
        if not h.auth.is_logged_in():
            abort(401)

        c.thinker = h.fetch_obj(Thinker, id)
        
        return render('thinker/thinker-edit.html')
    
    #UPDATE
    def update(self, id=None):
        terms = ['sep_dir', 'searchstring', 'wiki', 'birthday', 'deathday', 'label']
        super(ThinkerController, self).update(id, terms)

    @restrict('POST')
    def create(self):
        valid_params = ["sep_dir", "wiki"]
        EntityController.create(self,entity_type=3,valid_params=valid_params)
    
    def _thinker_evaluate(self, evaltype=None, id=None, id2=None, 
                            uid=None, username=None,
                            degree=1, maxdegree=1):
        """
        Private method to handle generic evaluations. See ``teacher_of`` and ``has_influenced``
        for use.
        """
        id2 = request.params.get('id2', id2)
        uid = request.params.get('uid', uid)
        username = request.params.get('username', username)
        evaluation = self._get_evaluation(evaltype, id, id2, uid, username)

        try:
            evaluation.degree = int(request.params.get('degree', degree))
        except TypeError:
            abort(400)

        # Create and commit evaluation
        Session.flush()

        # Issue an HTTP success
        response.status_int = 200
        return "OK"

    def _get_evaluation(self, evaltype, id, id2, uid=None, username=None, 
                        autoCreate=True):
        thinker1 = h.fetch_obj(Thinker, id)
        thinker2 = h.fetch_obj(Thinker, id2)

        # Get user information
        if uid:
            uid = h.fetch_obj(User, uid).ID
        elif username:
            user = h.get_user(username)
            uid = user.ID if user else abort(404)
        else:
            uid = h.get_user(request.environ['REMOTE_USER']).ID

        evaluation_q = Session.query(evaltype)
        evaluation = evaluation_q.filter_by(ante_id=id, cons_id=id2, 
                                            uid=uid).first()

        # if an evaluation does not yet exist, create one
        if autoCreate and not evaluation:
            evaluation = evaltype(id, id2, uid)
            Session.add(evaluation)

        return evaluation
    
    @restrict('DELETE')
    def _delete_evaluation(self, evaltype, id, id2, uid=None, username=None):
        id2 = request.params.get('id2', id2)
        uid = request.params.get('uid', uid)
        username = request.params.get('username', username)

        # look for a specific user's feedback
        evaluation = self._get_evaluation(evaltype, id, id2, uid, username, 
                                          autoCreate=False)
        
        # if that feedback does not exist, unleash the nuclear option and delete
        # ALL evaluation facts for this relation, wiping it from the database.
        if h.auth.is_admin() and not evaluation:
            eval_q = Session.query(evaltype)
            eval_q = eval_q.filter_by(ante_id=id, cons_id=id2)
            evals = eval_q.all()

            # wipe them out. all of them.
            for evaluation in evals:
                h.delete_obj(evaluation)
            
            # return ok, with how many were deleted
            response.status_int = 200
            return "OK %d" % len(evals)

        elif not evaluation:
            abort(404) # simply return an error (not evaluated), if not admin

        current_uid = h.get_user(request.environ['REMOTE_USER']).ID
        if evaluation.uid != current_uid and not h.auth.is_admin():
            abort(401)

        h.delete_obj(evaluation)

        response.status_int = 200
        return "OK"



    @dispatch_on(DELETE='_delete_unary')
    @restrict('POST', 'PUT')
    def unary(self, type, id, id2=None):
        thinker = h.fetch_obj(Thinker, id)

        id2 = request.params.get('id2', id2)
        obj = h.fetch_obj(unary_vars[type]['object'], id2)
        
        if obj not in getattr(thinker, unary_vars[type]['property']): 
            getattr(thinker, unary_vars[type]['property']).append(obj)

        Session.commit()

        response.status_int = 200
        return "OK"
    
    @restrict('DELETE')
    def _delete_unary(self, type, id, id2=None):
        thinker = h.fetch_obj(Thinker, id)

        id2 = request.params.get('id2', id2)
        obj = h.fetch_obj(unary_vars[type]['object'], id2)

        if obj in getattr(thinker, unary_vars[type]['property']):
            getattr(thinker, unary_vars[type]['property']).remove(obj)

        Session.commit()

        response.status_int = 200
        return "OK"

    @dispatch_on(DELETE='_delete_binary')
    @restrict('POST', 'PUT')
    def binary(self, type, id, id2, degree=1):
        if not h.auth.is_logged_in():
            abort(401)
        
        type = binary_vars[type]
        if type['reverse']:
            return self._thinker_evaluate(type['object'], id2, id, 
                                          degree=degree, 
                                          maxdegree=type['maxdegree'])
        else:
            return self._thinker_evaluate(type['object'], id, id2, 
                                          degree=degree, 
                                          maxdegree=type['maxdegree'])

    @restrict('DELETE')
    def _delete_binary(self, type, id, id2, degree=1):
        if not h.auth.is_logged_in():
            abort(401)

        type = binary_vars[type]

        if type['reverse']:
            return self._delete_evaluation(type['object'], id2, id)
        else:
            return self._delete_evaluation(type['object'], id, id2)
        
    def triple(self, id):
    
        c.entity = h.fetch_obj(Thinker, id)
        #parese the triple
        triple = request.params.get('triple').split()
        subject_t = triple[0]
        predicate_t = triple[1]
        objectURLComponents = triple[2].split('/')#parse triple for last
        check = "no teacher or student"
        #lastComponentIndex = objectURLComponents.__len__()-1
        object_t = objectURLComponents[-1]
        #- subject is the same as the id
        #- predicate is from the list and will be used in a if/elif/elif/elif/elif ... to see what database to add it to
        if "dbpedia.org" in objectURLComponents:
            object_t_label = object_t.replace("_"," ")
            obj = Thinker(object_t_label)
            obj.wiki = object_t
        elif "inpho.cogs.indiana.edu" in objectURLComponents:
            obj = h.fetch_obj(Thinker, object_t) 
        '''if(inpho):

            obj = h.fetch_obj(Thinker, object_t) # returns the SQLAlchemy object
           elif(dbpedia)
            obj = Thinker(object_t) # returns the SQLAlchemy object
        '''
        if predicate_t == 'ns1:influenced':
             c.entity.influenced.append(obj)
        elif predicate_t == 'ns1:influenced_by':
            c.entity.influenced_by.append(obj)
        elif predicate_t =='ns1:student':
            c.entity.students.append(obj)
        elif predicate_t == 'ns1:teacher':
            c.entity.teachers.append(obj)
        '''
        elif predicate == 'profession':

        elif predicate == 'birth_date':

        elif predicate == 'death_date':

        else predicate == 'nationality':
        '''
	
        Session.commit()
	subject_to_display=subject_t.split("/")[len(subject_t.split("/"))-1]
	predicate_to_display=predicate_t.split(":")[1]
	object_to_display=object_t
        return "OK : "+subject_to_display+" "+predicate_to_display+" "+object_to_display
