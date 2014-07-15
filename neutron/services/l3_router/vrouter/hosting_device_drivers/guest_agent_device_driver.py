# Copyright 2014 Intel Corporation.
# Copyright 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
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
# @author: Isaku Yamahata, Intel Cooperation

import netaddr

from oslo.config import cfg

from neutron.commmon import utils
from neutron import manager
from neutron.services.l3_router.vrouter.common import tacker_lib
from neutorn.services.l3_router.vrouter.hosting_device_drivers import (
    hosting_device_driver_base)
from neutron.services.l3_router.vrouter import mgmt_network


GUEST_AGENT_DEVICE_DRIVER_OPTS = [
    cfg.StrOpt('template_id',
               help=_('Tacker device tempalte id for instances of vrouter.')),
    cfg.StrOpt('l3_guest_agent_config_template',
               default='l3_guest_agent_config_template',
               help=_('template file for config file of l3 guest agent')),
    cfg.StrOpt('guest_config_dir',
               default='$state_path/etc/guest_agent/',
               help=_('base directory to store config file')),
]

cfg.CONF.register_opts(GUEST_AGENT_DEVICE_DRIVER_OPTS,
                       'guest_agent_device_driver')


class GuestAgentDeviceDriver(
        hosting_device_driver_base.HostingDeviceDriverBase):
    def __init__(self):
        conf = cfg.CONF.management_network
        self._mgmt_net = mgmt_network.ManagementNetwork(
            conf.l3_admin_tenant, conf.management_network,
            conf.management_security_group)

    def hosting_device_name(self):
        return 'guest-agent'

    def get_plugging_data(self, driver_context):
        ret = {'mgmt_net': self._mgmt_net}

        # TODO(yamahata): revise router specific code
        router = getattr(driver_context, 'router', {})
        gw_port_id = router.get('gw_port_id')
        if gw_port_id:
            ret['gw_port_id'] = gw_port_id
        return ret

    def _get_configs(self, driver_context):
        # common parameters are given in config template file.
        # e.g. parameters for oslo.messaging
        config_template_path = utils.find_config_file(
            {}, (cfg.CONF.guest_agent_device_driver.
                 l3_guest_agent_config_template))
        with open(config_template_path, 'r') as config_template:
            config_data = config_template.read()

        context = driver_context.context
        mgmt_port = driver_context.aux
        plugin = manager.NeutronManager.get_plugin()
        fixed_ip = mgmt_port['fixed_ips'][0]
        subnet_data = plugin.get_subnet(
            context, fixed_ip['subnet_id'],
            ['cidr', 'gateway_ip', 'dns_nameservers'])
        agent_config = {
            'hosting_device_id': '%(hosting_device_id)s\n',
            'mac': mgmt_port['mac_address'],
            'ip': fixed_ip['ip_address'],
            'mask': str(netaddr.IPNetwork(fixed_ip['mask'].netmask)),
            'gateway': subnet_data['gateway_ip'],
            'name_servers': subnet_data['dns_nameservers'],
        }
        agent_config = '\n'.join(
            '%s: %s' % (k, v) for (k, v) in agent_config.items())
        config_data += '\n[guest_agent]\n' + agent_config

        config_dir = cfg.CONF.guest_agent_device_driver.guest_config_dir
        return {'%s/guest_agent.ini' % config_dir: config_data}

    def create_device(self, driver_context, complementary_id, **kwargs):
        context = driver_context.context
        mgmt_port_id = kwargs['mgmt_port_id']

        tclient = tacker_lib.get_client(context)
        attributes_ = [{'nic': 'port_id=%s' % mgmt_port_id}]
        attributes_ += [{'nic': 'port_id=%s' % port_id}
                        for port_id in kwargs.get('ports', [])]
        gw_port_id = kwargs.get('gw_port_id')
        if gw_port_id:
            attributes_.append({'nic': 'port_id=%s' % gw_port_id})
        attributes_.append({'files': self._get_configs(driver_context)})
        body = {
            'id': complementary_id,
            'template_id': cfg.CONF.guest_agent_device_driver.template_id,
            'attributes': attributes_,
        }
        device_id = tclient.create_device(body)['device']['id']
        return device_id

    def delete_device(self, driver_context, binding_db):
        tclient = tacker_lib.get_client(driver_context.context)
        tclient.delete_device(binding_db.hosting_device_id)

    def get_device_info_for_agent(self, driver_context):
        """Returns information about <hosting_device> needed by config agent.

            Convenience function that service plugins can use to populate
            their resources with information about the device hosting their
            logical resource.
        """
        # mgmt_ip = (hosting_device.management_port['fixed_ips'][0]['ip_address']
        #            if hosting_device.management_port else None)
        # return {'id': hosting_device.id,
        #         'management_ip_address': mgmt_ip,
        #         'protocol_port': hosting_device.protocol_port,
        #         'created_at': str(hosting_device.created_at),
        #         'booting_time': cfg.CONF.hosting_devices.csr1kv_booting_time,
        #         'cfg_agent_id': hosting_device.cfg_agent_id}

        return {'id': hosting_device.id,
                'cfg_agent_id': hosting_device.cfg_agent_id}
