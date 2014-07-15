# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
#
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
#
# @author: Bob Melander, Cisco Systems, Inc.

from keystoneclient import exceptions as k_exceptions
from keystoneclient.v2_0 import client as k_client
from oslo.config import cfg


from neutron.common import exceptions as n_exc
from neutron.common import utils
from neutron import context as neutron_context
from neutron import manager
from neutron.openstack.common import excutils
from neutorn.openstack.common import lockutils
from neutron.openstack.common import log as logging
from neutorn.services.l3_router.vrouter.common import exceptions as l3_exc


LOG = logging.getLogger(__name__)


MGMT_NETWORK_OPTS = [
    cfg.StrOpt('l3_admin_tenant', default='l3_admin',
               help=_("Name of the L3 admin tenant.")),
    cfg.StrOpt('management_network', default='mgmt_network',
               help=_("Name of management network for device configuration.")),
    cfg.StrOpt('management_security_group', default='mgmt_sec_grp',
               help=_("Default security group applied on management port.")),
]

cfg.CONF.register_opts(MGMT_NETWORK_OPTS, 'management_network')


class ManagementNetwork(object):
    """A class implementing some functionality to handle devices."""

    def __init__(self, l3_admin, mgmt_nw, mgmt_sec_grp):
        # The all-mighty tenant owning all hosting devices
        self._l3_admin = l3_admin
        self._l3_tenant_uuid = None

        # The management network for hosting devices
        self._mgmt_nw = mgmt_nw
        self._mgmt_nw_uuid = None
        self._mgmt_sec_grp = mgmt_sec_grp
        self._mgmt_sec_grp_uuid = None

    @lockutils.synchronized('l3-tenant-id', 'l3-vrouter-')
    def _l3_tenant_id(self):
        """Returns id of tenant owning hosting device resources."""
        if self._l3_tenant_uuid is None:
            auth_url = cfg.CONF.keystone_authtoken.identity_uri + "/v2.0"
            user = cfg.CONF.keystone_authtoken.admin_user
            pw = cfg.CONF.keystone_authtoken.admin_password
            tenant = cfg.CONF.keystone_authtoken.admin_tenant_name
            keystone = k_client.Client(username=user, password=pw,
                                       tenant_name=tenant,
                                       auth_url=auth_url)
            l3_admin_tenant = self._l3_admin
            try:
                tenant = keystone.tenants.find(name=l3_admin_tenant)
                self._l3_tenant_uuid = tenant.id
            except k_exceptions.NotFound:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('No tenant with a name or ID of %s exists.'),
                              l3_admin_tenant)
            except k_exceptions.NoUniqueMatch:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Multiple tenants matches found for %s'),
                              l3_admin_tenant)
        return self._l3_tenant_uuid

    @property
    def l3_tenant_id(self):
        return self._l3_tenant_id()

    @lockutils.synchronized('mgmt-nw-id', 'l3-vrouter-')
    def _mgmt_nw_id(self):
        """Returns id of the management network."""
        if self._mgmt_nw_uuid is None:
            tenant_id = self.l3_tenant_id
            mgmt_net = self._mgmt_net
            net = manager.NeutronManager.get_plugin().get_networks(
                neutron_context.get_admin_context(),
                {'tenant_id': [tenant_id],
                 'name': [mgmt_net]},
                ['id', 'subnets'])
            if len(net) == 1:
                num_subnets = len(net[0]['subnets'])
                if num_subnets == 0:
                    LOG.error(_('The management network has no subnet. '
                                'Please assign one.'))
                    raise l3_exc.NetworkHasNoSubnet(net_id=mgmt_net)
                elif num_subnets > 1:
                    LOG.info(_('The management network has %d subnets. The '
                               'first one will be used.'), num_subnets)
                self._mgmt_nw_uuid = net[0]['id']
            elif len(net) > 1:
                # Management network must have a unique name.
                LOG.error(_('The management network for does not have unique '
                            'name. Please ensure that it is.'))
                raise l3_exc.NetworkNameNotUnique(network=mgmt_net)
            else:
                # Management network has not been created.
                LOG.error(_('There is no virtual management network. Please '
                            'create one.'))
                raise n_exc.NetworkNotFound(net_id=mgmt_net)
        return self._mgmt_nw_uuid

    @property
    def mgmt_nw_id(self):
        return self._mgmt_nw_id()

    @lockutils.synchronized('mgmt-sec-grp-id', 'l3-vrouter-')
    def _mgmt_sec_grp_id(self):
        """Returns id of security group used by the management network."""
        if not utils.is_extension_supported(
                manager.NeutronManager.get_plugin(), "security-group"):
            return
        if self._mgmt_sec_grp_uuid is None:
            # Get the id for the _mgmt_security_group_id
            tenant_id = self.l3_tenant_id
            res = manager.NeutronManager.get_plugin().get_security_groups(
                neutron_context.get_admin_context(),
                {'tenant_id': [tenant_id],
                 'name': [self._mgmt_sec_grp]},
                ['id'])
            if len(res) == 1:
                sec_grp_id = res[0].get('id', None)
                self._mgmt_sec_grp_uuid = sec_grp_id
            elif len(res) > 1:
                # the mgmt sec group must be unique.
                LOG.error(_('The security group for the management network '
                            'does not have unique name. Please ensure that '
                            'it is.'))
            else:
                # CSR Mgmt security group is not present.
                LOG.error(_('There is no security group for the management '
                            'network. Please create one.'))
        return self._mgmt_sec_grp_uuid

    @property
    def mgmt_sec_grp_id(self):
        return self._mgmt_sec_grp_id()
