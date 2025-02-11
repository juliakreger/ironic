#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Tests for the API /allocations/ methods.
"""

import datetime

import fixtures
import mock
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from six.moves import http_client
from six.moves.urllib import parse as urlparse
from wsme import types as wtypes

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import allocation as api_allocation
from ironic.api.controllers.v1 import notification_utils
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.objects import utils as obj_utils


class TestAllocationObject(base.TestCase):

    def test_allocation_init(self):
        allocation_dict = apiutils.allocation_post_data(node_id=None)
        del allocation_dict['extra']
        allocation = api_allocation.Allocation(**allocation_dict)
        self.assertEqual(wtypes.Unset, allocation.extra)


class TestListAllocations(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestListAllocations, self).setUp()
        self.node = obj_utils.create_test_node(self.context, name='node-1')

    def test_empty(self):
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual([], data['allocations'])

    def test_one(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(allocation.uuid, data['allocations'][0]["uuid"])
        self.assertEqual(allocation.name, data['allocations'][0]['name'])
        self.assertEqual({}, data['allocations'][0]["extra"])
        self.assertEqual(self.node.uuid, data['allocations'][0]["node_uuid"])
        # never expose the node_id
        self.assertNotIn('node_id', data['allocations'][0])

    def test_get_one(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])
        self.assertEqual({}, data["extra"])
        self.assertEqual(self.node.uuid, data["node_uuid"])
        # never expose the node_id
        self.assertNotIn('node_id', data)

    def test_get_one_with_json(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s.json' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_with_json_in_name(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      name='pg.json',
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_with_suffix(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      name='pg.1',
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_custom_fields(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        fields = 'resource_class,extra'
        data = self.get_json(
            '/allocations/%s?fields=%s' % (allocation.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertItemsEqual(['resource_class', 'extra', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)

        data = self.get_json(
            '/allocations?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['allocations']))
        for allocation in data['allocations']:
            # We always append "links"
            self.assertItemsEqual(['uuid', 'extra', 'links'], allocation)

    def test_get_custom_fields_invalid_fields(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/allocations/%s?fields=%s' % (allocation.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_one_invalid_api_version(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        response = self.get_json(
            '/allocations/%s' % (allocation.uuid),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_invalid_api_version_without_check(self):
        # Invalid name, but the check happens after the microversion check.
        response = self.get_json(
            '/allocations/ba!na!na!',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_many(self):
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(len(allocations), len(data['allocations']))

        uuids = [n['uuid'] for n in data['allocations']]
        six.assertCountEqual(self, allocations, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_allocation(self.context,
                                         uuid=uuid,
                                         node_id=self.node.id)
        data = self.get_json('/allocations/%s' % uuid, headers=self.headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for l in data['links']:
            bookmark = l['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(l['href'], bookmark=bookmark,
                                               headers=self.headers))

    def test_collection_links(self):
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations/?limit=3', headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

        next_marker = data['allocations'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

        next_marker = data['allocations'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'node_uuid'
        limit = 2
        allocations = []
        for id_ in range(3):
            allocation = obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation)

        data = self.get_json(
            '/allocations?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['allocations']))
        self.assertIn('marker=%s' % allocations[limit - 1].uuid, data['next'])

    def test_allocation_get_all_invalid_api_version(self):
        obj_utils.create_test_allocation(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            name='allocation_1')
        response = self.get_json('/allocations',
                                 headers={api_base.Version.string: '1.14'},
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_sort_key(self):
        allocations = []
        for id_ in range(3):
            allocation = obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations?sort_key=uuid',
                             headers=self.headers)
        uuids = [n['uuid'] for n in data['allocations']]
        self.assertEqual(sorted(allocations), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra', 'internal_info', 'properties']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/allocations?sort_key=%s' % invalid_key,
                                     expect_errors=True, headers=self.headers)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def test_sort_key_allowed(self):
        allocation_uuids = []
        for id_ in range(3, 0, -1):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocation_uuids.append(allocation.uuid)
        allocation_uuids.reverse()
        data = self.get_json('/allocations?sort_key=name',
                             headers=self.headers)
        data_uuids = [p['uuid'] for p in data['allocations']]
        self.assertEqual(allocation_uuids, data_uuids)

    def test_get_all_by_state(self):
        for i in range(5):
            if i < 3:
                state = 'allocating'
            else:
                state = 'active'
            obj_utils.create_test_allocation(
                self.context,
                state=state,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
        data = self.get_json("/allocations?state=allocating",
                             headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

    def test_get_all_by_node_name(self):
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_allocation(
                self.context,
                node_id=node_id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
        data = self.get_json("/allocations?node=%s" % self.node.name,
                             headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

    def test_get_all_by_node_uuid(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        data = self.get_json('/allocations?node=%s' % (self.node.uuid),
                             headers=self.headers)
        self.assertEqual(1, len(data['allocations']))

    def test_get_all_by_non_existing_node(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.get_json('/allocations?node=banana',
                                 headers=self.headers, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_get_by_node_resource(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/nodes/%s/allocation' % self.node.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])
        self.assertEqual({}, data["extra"])
        self.assertEqual(self.node.uuid, data["node_uuid"])

    def test_get_by_node_resource_invalid_api_version(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.get_json(
            '/nodes/%s/allocation' % self.node.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_by_node_resource_with_fields(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        data = self.get_json('/nodes/%s/allocation?fields=name,extra' %
                             self.node.uuid,
                             headers=self.headers)
        self.assertNotIn('uuid', data)
        self.assertIn('name', data)
        self.assertEqual({}, data["extra"])

    def test_get_by_node_resource_and_id(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        response = self.get_json('/nodes/%s/allocation/%s' % (self.node.uuid,
                                                              allocation.uuid),
                                 headers=self.headers, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_by_node_resource_not_existed(self):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid())
        res = self.get_json('/node/%s/allocation' % node.uuid,
                            expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_by_node_invalid_node(self):
        res = self.get_json('/node/%s/allocation' % uuidutils.generate_uuid(),
                            expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)


class TestPatch(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPatch, self).setUp()
        self.allocation = obj_utils.create_test_allocation(self.context)

    def test_update_not_allowed(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)


def _create_locally(_api, _ctx, allocation, _topic):
    allocation.create()
    return allocation


@mock.patch.object(rpcapi.ConductorAPI, 'create_allocation', _create_locally)
class TestPost(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPost, self).setUp()
        self.mock_get_topic = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_random_topic')
        ).mock
        self.mock_get_topic.return_value = 'some-topic'

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_create_allocation(self, mock_utcnow, mock_notify):
        adict = apiutils.allocation_post_data()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(adict['uuid'], response.json['uuid'])
        self.assertEqual('allocating', response.json['state'])
        self.assertIsNone(response.json['node_uuid'])
        self.assertEqual([], response.json['candidate_nodes'])
        self.assertEqual([], response.json['traits'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        self.assertIsNone(result['node_uuid'])
        self.assertEqual([], result['candidate_nodes'])
        self.assertEqual([], result['traits'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/allocations/%s' % adict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START),
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END),
        ])

    def test_create_allocation_invalid_api_version(self):
        adict = apiutils.allocation_post_data()
        response = self.post_json(
            '/allocations', adict, headers={api_base.Version.string: '1.50'},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_create_allocation_doesnt_contain_id(self):
        with mock.patch.object(self.dbapi, 'create_allocation',
                               wraps=self.dbapi.create_allocation) as cp_mock:
            adict = apiutils.allocation_post_data(extra={'foo': 123})
            self.post_json('/allocations', adict, headers=self.headers)
            result = self.get_json('/allocations/%s' % adict['uuid'],
                                   headers=self.headers)
            self.assertEqual(adict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', cp_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_allocation_generate_uuid(self, mock_warn, mock_except):
        adict = apiutils.allocation_post_data()
        del adict['uuid']
        response = self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warn.called)
        self.assertFalse(mock_except.called)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(objects.Allocation, 'create')
    def test_create_allocation_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        adict = apiutils.allocation_post_data()
        self.post_json('/allocations', adict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START),
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.ERROR,
                      obj_fields.NotificationStatus.ERROR),
        ])

    def test_create_allocation_with_candidate_nodes(self):
        node1 = obj_utils.create_test_node(self.context,
                                           name='node-1')
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid())
        adict = apiutils.allocation_post_data(
            candidate_nodes=[node1.name, node2.uuid])
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual([node1.uuid, node2.uuid], result['candidate_nodes'])

    def test_create_allocation_valid_extra(self):
        adict = apiutils.allocation_post_data(
            extra={'str': 'foo', 'int': 123, 'float': 0.1, 'bool': True,
                   'list': [1, 2], 'none': None, 'dict': {'cat': 'meow'}})
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['extra'], result['extra'])

    def test_create_allocation_with_no_extra(self):
        adict = apiutils.allocation_post_data()
        del adict['extra']
        response = self.post_json('/allocations', adict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)

    def test_create_allocation_no_mandatory_field_resource_class(self):
        adict = apiutils.allocation_post_data()
        del adict['resource_class']
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_resource_class_too_long(self):
        adict = apiutils.allocation_post_data()
        adict['resource_class'] = 'f' * 81
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_with_traits(self):
        adict = apiutils.allocation_post_data()
        adict['traits'] = ['CUSTOM_GPU', 'CUSTOM_FOO_BAR']
        response = self.post_json('/allocations', adict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(['CUSTOM_GPU', 'CUSTOM_FOO_BAR'],
                         response.json['traits'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(['CUSTOM_GPU', 'CUSTOM_FOO_BAR'],
                         result['traits'])

    def test_create_allocation_invalid_trait(self):
        adict = apiutils.allocation_post_data()
        adict['traits'] = ['CUSTOM_GPU', 'FOO_BAR']
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_invalid_candidate_node_format(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['invalid-format'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_candidate_node_not_found(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_candidate_node_invalid(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['this/is/not a/node/name'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_name_ok(self):
        name = 'foo'
        adict = apiutils.allocation_post_data(name=name)
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(name, result['name'])

    def test_create_allocation_name_invalid(self):
        name = 'aa:bb_cc'
        adict = apiutils.allocation_post_data(name=name)
        response = self.post_json('/allocations', adict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_create_by_node_not_allowed(self):
        node = obj_utils.create_test_node(self.context)
        adict = apiutils.allocation_post_data()
        response = self.post_json('/nodes/%s/allocation' % node.uuid,
                                  adict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_create_with_node_uuid_not_allowed(self):
        adict = apiutils.allocation_post_data()
        adict['node_uuid'] = uuidutils.generate_uuid()
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_allocation')
class TestDelete(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.allocation = obj_utils.create_test_allocation(
            self.context, node_id=self.node.id, name='alloc1')

        self.mock_get_topic = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_random_topic')
        ).mock

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_allocation_by_id(self, mock_notify, mock_destroy):
        self.delete('/allocations/%s' % self.allocation.uuid,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END,
                      node_uuid=self.node.uuid),
        ])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_allocation_node_locked(self, mock_notify, mock_destroy):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_destroy.side_effect = exception.NodeLocked(node='fake-node',
                                                        host='fake-host')
        ret = self.delete('/allocations/%s' % self.allocation.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.CONFLICT, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.ERROR,
                      obj_fields.NotificationStatus.ERROR,
                      node_uuid=self.node.uuid),
        ])

    def test_delete_allocation_invalid_api_version(self, mock_destroy):
        response = self.delete('/allocations/%s' % self.allocation.uuid,
                               expect_errors=True,
                               headers={api_base.Version.string: '1.14'})
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_delete_allocation_invalid_api_version_without_check(self,
                                                                 mock_destroy):
        # Invalid name, but the check happens after the microversion check.
        response = self.delete('/allocations/ba!na!na1',
                               expect_errors=True,
                               headers={api_base.Version.string: '1.14'})
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_delete_allocation_by_name(self, mock_destroy):
        self.delete('/allocations/%s' % self.allocation.name,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)

    def test_delete_allocation_by_name_with_json(self, mock_destroy):
        self.delete('/allocations/%s.json' % self.allocation.name,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)

    def test_delete_allocation_by_name_not_existed(self, mock_destroy):
        res = self.delete('/allocations/%s' % 'blah', expect_errors=True,
                          headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_allocation_by_node(self, mock_notify, mock_destroy):
        self.delete('/nodes/%s/allocation' % self.node.uuid,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END,
                      node_uuid=self.node.uuid),
        ])

    def test_delete_allocation_by_node_not_existed(self, mock_destroy):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid())
        res = self.delete('/nodes/%s/allocation' % node.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_delete_allocation_invalid_node(self, mock_destroy):
        res = self.delete('/nodes/%s/allocation' % uuidutils.generate_uuid(),
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_delete_allocation_by_node_invalid_api_version(self, mock_destroy):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.delete(
            '/nodes/%s/allocation' % self.node.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertFalse(mock_destroy.called)
