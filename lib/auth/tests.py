# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from mock import Mock
from nose.tools import eq_, ok_
import ldap

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User, Group

# lib.auth.backends expects the LDAP_* to be set up
# fake that so we can import MozLdapBackend
settings.LDAP_HOST = settings.LDAP_DN = settings.LDAP_PASSWORD = 'test'
from lib.auth.backends import MozLdapBackend


class BreakingMozLdapBackend(MozLdapBackend):

    def _authenticate_ldap(self, *a, **k):
        raise ldap.SERVER_DOWN("Unable to connect")


class MockLDAP:
    def __init__(self, search_result, credentials=None):
        self.search_result = search_result
        self.credentials = credentials

    def search_s(self, search, *args, **kargs):
        return self.search_result[search]

    def simple_bind_s(self, dn, password):
        # to simulate how _ldap works we have to have byte strings here
        assert isinstance(dn, str)
        assert isinstance(password, str)
        if self.credentials is None:
            # password check passed
            return
        if dn == settings.LDAP_DN:
            # sure, pretend we can connect successfully
            return
        try:
            if self.credentials[dn] != password:
                raise ldap.INVALID_CREDENTIALS
        except KeyError:
            raise ldap.UNWILLING_TO_PERFORM

    def void(self, *args, **kwargs):
        pass

    set_option = unbind_s = void


class LDAPAuthTestCase(TestCase):

    def setUp(self):
        super(LDAPAuthTestCase, self).setUp()
        self.fake_user = [
          ('mail=pbengtsson@mozilla.com,o=com,dc=mozilla',
           {'givenName': ['Pet\xc3\xa3r'],  # utf-8 encoded
            'mail': ['peterbe@mozilla.com'],
            'sn': ['Bengtss\xc2\xa2n'],
            'uid': ['pbengtsson']
            })
        ]

        self.fake_group = [
          ('cn=scm_l10n,ou=groups,dc=mozilla',
           {'cn': ['scm_l10n']})
        ]

        # make sure there are certain groups available
        Group.objects.get_or_create(name='Localizers')
        Group.objects.get_or_create(name='build')

    def test_authenticate_without_ldap(self):
        assert not User.objects.all().exists()
        user = User.objects.create(username='foo', email='foo@mozilla.com')
        user.set_password('secret')
        user.save()

        backend = MozLdapBackend()
        eq_(backend.authenticate('foo@mozilla.com', 'secret'),
                         user)
        eq_(backend.authenticate('foo', 'secret'), user)
        eq_(backend.authenticate('foo', 'JUNK'), None)

    def test_backend_cert_file(self):
        backend = MozLdapBackend()
        ok_(backend.certfile)
        ok_(os.path.isfile(os.path.abspath(backend.certfile)))

    def test_authenticate_with_ldap_new_user(self):
        assert not User.objects.all().exists()
        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }))
        backend = MozLdapBackend()

        user = backend.authenticate('foo', 'secret')
        ok_(user)
        ok_(User.objects.get(username='foo'))
        user = User.objects.get(first_name=u'Pet\xe3r')
        eq_(user.last_name, u'Bengtss\xa2n')
        ok_(not user.has_usable_password())
        ok_(not user.check_password('secret'))
        ok_(user.groups.filter(name='Localizers').exists())

    def test_authenticate_with_ldap_new_user_with_long_email(self):
        assert not User.objects.all().exists()
        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        long_email = 'peter.anders.bengt.bengtsson@mozilla-europe.org.com'
        fake_user = [
          ('mail=%s,...' % long_email,
           {'cn': ['Peter Bengtsson'],
            'givenName': ['Pet\xc3\xa3r'],  # utf-8 encoded
            'mail': [long_email],
            'sn': ['Bengtss\xc2\xa2n'],
            'uid': ['pbengtsson']
            })
        ]

        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }))
        backend = MozLdapBackend()

        user = backend.authenticate(long_email, 'secret')
        ok_(user)
        ok_(User.objects.get(email=long_email))
        ok_(len(User.objects.get(email=long_email).username) <= 30)
        user = User.objects.get(first_name=u'Pet\xe3r')
        eq_(user.last_name, u'Bengtss\xa2n')
        ok_(not user.has_usable_password())
        ok_(not user.check_password('secret'))

    def test_authenticate_with_non_ascii_mail(self):
        assert not User.objects.all().exists()
        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        email = u'm\xc3@example.com'
        fake_user = [
          ('mail=%s,...' % email,
           {'cn': ['Peter Bengtsson'],
            'givenName': ['Peter'],
            'mail': [email],
            'sn': ['Bengtsson'],
            'uid': ['pbengtsson']
            })
        ]

        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }))
        backend = MozLdapBackend()

        user = backend.authenticate(email, 'secret')
        ok_(user)
        ok_(User.objects.get(email=email))

    def test_authenticate_with_non_ascii_password(self):
        assert not User.objects.all().exists()
        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        email = 'meh@example.com'
        fake_user = [
          ('mail=%s,...' % email,
           {'cn': ['Peter Bengtsson'],
            'givenName': ['Peter'],
            'mail': [email],
            'sn': ['Bengtsson'],
            'uid': ['pbengtsson']
            })
        ]

        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }))
        backend = MozLdapBackend()

        user = backend.authenticate(email, u's\xc4cret')
        ok_(user)
        ok_(User.objects.get(email=email))

    def test_authenticate_with_ldap_existing_user(self):
        assert not User.objects.all().exists()
        user = User.objects.create(
          username='foo',
          first_name=u'P\xe4ter',
          last_name=u'B\xa3ngtsson',
        )
        assert user.groups.all().count() == 0
        user.set_unusable_password()
        user.save()

        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }))
        backend = MozLdapBackend()

        user = backend.authenticate('foo', 'secret')
        ok_(user)
        _first_name = self.fake_user[0][1]['givenName'][0]
        eq_(user.first_name, unicode(_first_name, 'utf-8'))
        _last_name = self.fake_user[0][1]['sn'][0]
        eq_(user.last_name, unicode(_last_name, 'utf-8'))
        eq_(user.email, self.fake_user[0][1]['mail'][0])

        user_saved = User.objects.get(username='foo')
        eq_(user_saved.first_name, user.first_name)
        eq_(user_saved.last_name, user.last_name)

        ok_(user_saved.groups.filter(name='Localizers').exists())

    def test_authenticate_with_ldap_wrong_password(self):
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }, credentials={
          self.fake_user[0][0]: 'rightsecret'
        }))
        backend = MozLdapBackend()
        user = backend.authenticate('foo', 'secret')
        eq_(user, None)

    def test_authenticate_with_ldap_wrong_username(self):
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': self.fake_group
        }, credentials={
          'some-other-uid': 'secret'
        }))
        backend = MozLdapBackend()
        user = backend.authenticate('foo', 'secret')
        eq_(user, None)

    def test_authentication_ldap_username_not_recognized(self):
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': None,
          'ou=groups,dc=mozilla': self.fake_group
        }, credentials={
          self.fake_user[0][0]: 'secret'
        }))
        backend = MozLdapBackend()
        user = backend.authenticate('foo', 'secret')
        ok_(not user)

    def test_ldap_server_down_error(self):
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': None,
          'ou=groups,dc=mozilla': self.fake_group
        }, credentials={
          self.fake_user[0][0]: 'secret'
        }))
        backend = BreakingMozLdapBackend()
        self.assertRaises(ldap.SERVER_DOWN, backend.authenticate,
                          'foo', 'secret')

        # try it from the "outside"
        from django.core.urlresolvers import reverse
        url = reverse('accounts.views.login')
        settings_before = settings.AUTHENTICATION_BACKENDS

        try:
            settings.AUTHENTICATION_BACKENDS = (
              'lib.auth.tests.BreakingMozLdapBackend',
            )
            response = self.client.post(url,
                                     {'username': 'foo', 'password': 'secret'})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.content, 'Service Unavailable')
        finally:
            settings.AUTHENTICATION_BACKENDS = settings_before

    def test_lost_group_privileges(self):
        # test a user that is part of the `Localizers` group one day but not
        # the other

        assert not User.objects.all().exists()
        ldap.open = Mock('ldap.open')
        ldap.open.mock_returns = Mock('ldap_connection')
        ldap.set_option = Mock(return_value=None)

        groups = [
          ('cn=scm_l10n,ou=groups,dc=mozilla',
           {'cn': ['scm_l10n']}),
          ('cn=buildteam,ou=groups,dc=mozilla',
           {'cn': ['buildteam']})
        ]
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': groups
        }))
        backend = MozLdapBackend()

        user = backend.authenticate('foo', 'secret')
        assert user == User.objects.get()
        ok_(user.groups.filter(name='Localizers').exists())
        ok_(user.groups.filter(name='build').exists())

        new_groups = [
          ('cn=buildteam,ou=groups,dc=mozilla',
           {'cn': ['buildteam']})
        ]
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': new_groups
        }))

        user = backend.authenticate('foo', 'secret')
        assert user == User.objects.get()
        ok_(not user.groups.filter(name='Localizers').exists())
        ok_(user.groups.filter(name='build').exists())

        # Now reverse it
        new_new_groups = [
          ('cn=scm_l10n,ou=groups,dc=mozilla',
           {'cn': ['scm_l10n']})
        ]
        ldap.initialize = Mock(return_value=MockLDAP({
          'dc=mozilla': self.fake_user,
          'ou=groups,dc=mozilla': new_new_groups
        }))

        user = backend.authenticate('foo', 'secret')
        assert user == User.objects.get()
        ok_(user.groups.filter(name='Localizers').exists())
        ok_(not user.groups.filter(name='build').exists())
