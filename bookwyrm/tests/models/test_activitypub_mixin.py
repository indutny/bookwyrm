''' testing model activitypub utilities '''
from unittest.mock import patch
from collections import namedtuple
from dataclasses import dataclass
import re
from django.test import TestCase

from bookwyrm.activitypub.base_activity import ActivityObject
from bookwyrm import models
from bookwyrm.models import base_model
from bookwyrm.models.activitypub_mixin import ActivitypubMixin
from bookwyrm.models.activitypub_mixin import ActivityMixin, ObjectMixin

class ActivitypubMixins(TestCase):
    ''' functionality shared across models '''
    def setUp(self):
        ''' shared data '''
        self.local_user = models.User.objects.create_user(
            'mouse', 'mouse@mouse.com', 'mouseword',
            local=True, localname='mouse')
        self.local_user.remote_id = 'http://example.com/a/b'
        self.local_user.save(broadcast=False)


    # ActivitypubMixin
    def test_to_activity(self):
        ''' model to ActivityPub json '''
        @dataclass(init=False)
        class TestActivity(ActivityObject):
            ''' real simple mock '''
            type: str = 'Test'

        class TestModel(ActivitypubMixin, base_model.BookWyrmModel):
            ''' real simple mock model because BookWyrmModel is abstract '''

        instance = TestModel()
        instance.remote_id = 'https://www.example.com/test'
        instance.activity_serializer = TestActivity

        activity = instance.to_activity()
        self.assertIsInstance(activity, dict)
        self.assertEqual(activity['id'], 'https://www.example.com/test')
        self.assertEqual(activity['type'], 'Test')


    def test_find_existing_by_remote_id(self):
        ''' attempt to match a remote id to an object in the db '''
        # uses a different remote id scheme
        # this isn't really part of this test directly but it's helpful to state
        book = models.Edition.objects.create(
            title='Test Edition', remote_id='http://book.com/book')

        self.assertEqual(book.origin_id, 'http://book.com/book')
        self.assertNotEqual(book.remote_id, 'http://book.com/book')

        # uses subclasses
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            models.Comment.objects.create(
                user=self.local_user, content='test status', book=book, \
                remote_id='https://comment.net')

        result = models.User.find_existing_by_remote_id('hi')
        self.assertIsNone(result)

        result = models.User.find_existing_by_remote_id(
            'http://example.com/a/b')
        self.assertEqual(result, self.local_user)

        # test using origin id
        result = models.Edition.find_existing_by_remote_id(
            'http://book.com/book')
        self.assertEqual(result, book)

        # test subclass match
        result = models.Status.find_existing_by_remote_id(
            'https://comment.net')


    def test_find_existing(self):
        ''' match a blob of data to a model '''
        book = models.Edition.objects.create(
            title='Test edition',
            openlibrary_key='OL1234',
        )

        result = models.Edition.find_existing(
            {'openlibraryKey': 'OL1234'})
        self.assertEqual(result, book)


    def test_get_recipients(self):
        ''' determines the recipients for a broadcast '''
        MockSelf = namedtuple('Self', ('privacy'))
        mock_self = MockSelf('public')
        ActivitypubMixin.get_recipients(mock_self)
        


    # ObjectMixin
    def test_to_create_activity(self):
        ''' wrapper for ActivityPub "create" action '''
        object_activity = {
            'to': 'to field', 'cc': 'cc field',
            'content': 'hi',
            'published': '2020-12-04T17:52:22.623807+00:00',
        }
        MockSelf = namedtuple('Self', ('remote_id', 'to_activity'))
        mock_self = MockSelf(
            'https://example.com/status/1',
            lambda *args: object_activity
        )
        activity = ObjectMixin.to_create_activity(
            mock_self, self.local_user)
        self.assertEqual(
            activity['id'],
            'https://example.com/status/1/activity'
        )
        self.assertEqual(activity['actor'], self.local_user.remote_id)
        self.assertEqual(activity['type'], 'Create')
        self.assertEqual(activity['to'], 'to field')
        self.assertEqual(activity['cc'], 'cc field')
        self.assertEqual(activity['object'], object_activity)
        self.assertEqual(
            activity['signature'].creator,
            '%s#main-key' % self.local_user.remote_id
        )

    def test_to_delete_activity(self):
        ''' wrapper for Delete activity '''
        MockSelf = namedtuple('Self', ('remote_id', 'to_activity'))
        mock_self = MockSelf(
            'https://example.com/status/1',
            lambda *args: {}
        )
        activity = ObjectMixin.to_delete_activity(
            mock_self, self.local_user)
        self.assertEqual(
            activity['id'],
            'https://example.com/status/1/activity'
        )
        self.assertEqual(activity['actor'], self.local_user.remote_id)
        self.assertEqual(activity['type'], 'Delete')
        self.assertEqual(
            activity['to'],
            ['%s/followers' % self.local_user.remote_id])
        self.assertEqual(
            activity['cc'],
            ['https://www.w3.org/ns/activitystreams#Public'])


    def test_to_update_activity(self):
        ''' ditto above but for Update '''
        MockSelf = namedtuple('Self', ('remote_id', 'to_activity'))
        mock_self = MockSelf(
            'https://example.com/status/1',
            lambda *args: {}
        )
        activity = ObjectMixin.to_update_activity(
            mock_self, self.local_user)
        self.assertIsNotNone(
            re.match(
                r'^https:\/\/example\.com\/status\/1#update\/.*',
                activity['id']
            )
        )
        self.assertEqual(activity['actor'], self.local_user.remote_id)
        self.assertEqual(activity['type'], 'Update')
        self.assertEqual(
            activity['to'],
            ['https://www.w3.org/ns/activitystreams#Public'])
        self.assertEqual(activity['object'], {})


    # Activity mixin
    def test_to_undo_activity(self):
        ''' and again, for Undo '''
        MockSelf = namedtuple('Self', ('remote_id', 'to_activity', 'user'))
        mock_self = MockSelf(
            'https://example.com/status/1',
            lambda *args: {},
            self.local_user,
        )
        activity = ActivityMixin.to_undo_activity(mock_self)
        self.assertEqual(
            activity['id'],
            'https://example.com/status/1#undo'
        )
        self.assertEqual(activity['actor'], self.local_user.remote_id)
        self.assertEqual(activity['type'], 'Undo')
        self.assertEqual(activity['object'], {})
