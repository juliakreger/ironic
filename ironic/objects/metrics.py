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

from oslo_utils import strutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class NodeMetric(base.IronicObject,
                   object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'node_id': object_fields.IntegerField(nullable=False),
        'metrics': object_fields.FlexibleDictField(nullable=True),
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    def get(self, context, ident):
        """Find a node metric document based on its ID.

        :param context: security context
        :param ident: the node_id value for which this metric is desired.
        :returns: a :class:`NodeMetric` object
        """
        if strutils.is_int_like(ident):
            return self.get_by_id(context, ident)
        else:
            raise exception.InvalidIdentity(identity=ident)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, db_id):
        """TODO.
        """
        db = cls.dbapi.get_node_metrics(db_id)
        metric = cls._from_db_object(context, cls(), db)
        return metric

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this VolumeTarget.

        Updates will be made column by column based on the result
        of self.do_version_changes_for_db().

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: NodeMetric(context).
        """
        updates = self.do_version_changes_for_db()
        updated_metric = self.dbapi.save_node_metrics(self.node_id,
                                                      self.metrics)
        self._from_db_object(self._context, self, updated_metric)
