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

from oslo.config import cfg

from neutron.db import agents_db
from neutron.db import api as qdbapi
from neutron.db import common_db_mixin
from neutron import manager
from neutron.openstack.common import importutils
from neutron.services.l3_router.vrouter.db import device_handling_db
from neutron.services.l3_router.vrouter.db import l3_vrouter_db
from neutron.plugins.common import constants


class L3VRouterPlugin(common_db_mixin.CommonDbMixin,
                    agents_db.AgentDbMixin,
                    l3_vrouter_db.L3VRouterDbMixin,
                    device_handling_db.DeviceHandlingMixin):

    """Implementation of L3 Router Hosting Device Service Plugin for Neutron.

    This class implements a L3 service plugin that provides
    router and floatingip resources and manages associated
    request/response.
    All DB functionality is implemented in class
    l3_router_appliance_db.L3RouterApplianceDBMixin.
    """
    supported_extension_aliases = ["router", "extraroute"]

    def __init__(self):
        qdbapi.register_models()
        super(L3VRouterPlugin, self).__init__()
        self.initialize()
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver)

        # TODO:XXX
        # for backlogging of non-scheduled routers
        self._setup_backlog_handling()
        self._setup_device_handling()

    def get_plugin_type(self):
        return constants.L3_ROUTER_NAT

    def get_plugin_description(self):
        return ("Router Hosting Device Service Plugin for basic L3 forwarding"
                " between (L2) Neutron networks and access to external"
                " networks via a NAT gateway.")

    @property
    def _core_plugin(self):
        return manager.NeutronManager.get_plugin()
