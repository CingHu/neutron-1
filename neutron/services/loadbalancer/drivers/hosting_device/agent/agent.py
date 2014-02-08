# Copyright 2014 Intel Corporation.
# Copyright 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
# All Rights Reserved.
#
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
# @author: Isaku Yamahata, Intel Corporation.

import inspect
import os
import shutil
import socket

import eventlet
from oslo.config import cfg

from neutron.agent.common import config
from neutron.agent.linux import interface
from neutron.agent.linux import ip_lib
from neutron.common import legacy
from neutron.common import topics
from neutron.common import utils as n_utils
from neutron import context
from neutron import manager
from neutron.openstack.common import log as logging
from neutron.openstack.common import service
from neutron.plugins.common import constants
from neutron import service as neutron_service
from neutron.services.loadbalancer.agent import agent_api
from neutron.services.loadbalancer.drivers.haproxy import cfg as hacfg
from neutron.services.loadbalancer.drivers.haproxy import namespace_driver
from neutron.vm.mgmt_drivers import constants as mgmt_constants
from neutron.vm.mgmt_drivers.rpc import config as rpc_config


LOG = logging.getLogger(__name__)
kill_pids_in_file = namespace_driver.kill_pids_in_file


def _log_debug(self):
    (frame, _filename, _line_number, function_name, _lines,
     _index) = inspect.stack()[1]
    arg_info = inspect.getargvalues(frame)
    LOG.debug(_('%(function_name)s called with %(arg_info)s'),
              {'function_name': function_name, 'arg_info': arg_info})


# all run in root netns
def get_ns_name(namespace_id):
    return None


# mostly same to
# neutron.services.loadbalancer.driver.haproxy.namespace_driver.HaproxyNSDriver
# but run in root ns
class ServiceInstanceDriver(namespace_driver.HaproxyNSDriver):
    @classmethod
    def get_name(cls):
        return cls.__name__

    def create(self, logical_config):
        pool_id = logical_config['pool']['id']
        namespace = get_ns_name(pool_id)

        self._plug(namespace, logical_config['vip']['port'])
        self._spawn(logical_config)

    def _spawn(self, logical_config, extra_cmd_args=()):
        pool_id = logical_config['pool']['id']
        namespace = get_ns_name(pool_id)
        conf_path = self._get_state_file_path(pool_id, 'conf')
        pid_path = self._get_state_file_path(pool_id, 'pid')
        sock_path = self._get_state_file_path(pool_id, 'sock')
        user_group = self.conf.haproxy.user_group

        hacfg.save_config(conf_path, logical_config, sock_path, user_group)
        cmd = ['haproxy', '-f', conf_path, '-p', pid_path]
        cmd.extend(extra_cmd_args)

        ns = ip_lib.IPWrapper(self.root_helper, namespace)
        ns.netns.execute(cmd)

        # remember the pool<>port mapping
        self.pool_to_port_id[pool_id] = logical_config['vip']['port']['id']

    @n_utils.synchronized('haproxy-driver')
    def undeploy_instance(self, pool_id):
        namespace = get_ns_name(pool_id)
        ns = ip_lib.IPWrapper(self.root_helper, namespace)
        pid_path = self._get_state_file_path(pool_id, 'pid')

        # kill the process
        kill_pids_in_file(self.root_helper, pid_path)

        # # unplug the ports
        # if pool_id in self.pool_to_port_id:
        #     self._unplug(namespace, self.pool_to_port_id[pool_id])

        # remove the configuration directory
        conf_dir = os.path.dirname(self._get_state_file_path(pool_id, ''))
        if os.path.isdir(conf_dir):
            shutil.rmtree(conf_dir)
        ns.garbage_collect_namespace()

    def exists(self, pool_id):
        namespace = get_ns_name(pool_id)
        root_ns = ip_lib.IPWrapper(self.root_helper)

        socket_path = self._get_state_file_path(pool_id, 'sock')
        if root_ns.netns.exists(namespace) and os.path.exists(socket_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(socket_path)
                return True
            except socket.error:
                pass
        return False

    def _plug(self, namespace, port, reuse_existing=True):
        # self.plugin_rpc.plug_vip_port(port['id'])
        # interface_name = self.vif_driver.get_device_name(Wrap(port))

        # if ip_lib.device_exists(interface_name, self.root_helper, namespace):
        #     if not reuse_existing:
        #         raise exceptions.PreexistingDeviceFailure(
        #             dev_name=interface_name
        #         )
        # else:
        #     self.vif_driver.plug(
        #         port['network_id'],
        #         port['id'],
        #         interface_name,
        #         port['mac_address'],
        #         namespace=namespace
        #     )

        # cidrs = [
        #     '%s/%s' % (ip['ip_address'],
        #                netaddr.IPNetwork(ip['subnet']['cidr']).prefixlen)
        #     for ip in port['fixed_ips']
        # ]
        # self.vif_driver.init_l3(interface_name, cidrs, namespace=namespace)

        gw_ip = port['fixed_ips'][0]['subnet'].get('gateway_ip')
        if gw_ip:
            cmd = ['route', 'add', 'default', 'gw', gw_ip]
            ip_wrapper = ip_lib.IPWrapper(self.root_helper,
                                          namespace=namespace)
            ip_wrapper.netns.execute(cmd, check_exit_code=False)

    def _unplug(self, namespace, port_id):
        # port_stub = {'id': port_id}
        # self.plugin_rpc.unplug_vip_port(port_id)
        # interface_name = self.vif_driver.get_device_name(Wrap(port_stub))
        # self.vif_driver.unplug(interface_name, namespace=namespace)
        raise RuntimeError(_('_unplug should not be called'))


# TODO(yamahata): periodic resync, agent_updated
class ServiceInstanceAgent(manager.Manager):
    @classmethod
    def create(cls, conf, topic, device, service_instance, mgmt_kwargs):
        host = service_instance['id']
        topic_ = '%s-%s' % (topic, device['id'])
        mgr = cls(conf, topic_, device, service_instance, mgmt_kwargs)
        return neutron_service.Service(host=host, topic=topic, mgr=mgr)

    def __init__(self, conf, topic, device, service_instance, mgmt_kwargs):
        service_instance_id = service_instance['id']
        self.context = context.get_admin_context_without_session()
        self.plugin_rpc = agent_api.LbaasAgentApi(
            topics.LOADBALANCER_PLUGIN, self.context, service_instance_id)
        self._driver = ServiceInstanceDriver(conf, self.plugin_rpc)
        super(ServiceInstanceAgent, self).__init__(host=service_instance_id)

    def create_service(self, device, service_instance, mgmt_kwargs):
        _log_debug()

    # called when vip/pool/member/health-monitor are created/updated/deleted
    def update_service(self, device, service_instance, mgmt_kwargs):
        method = mgmt_kwargs[mgmt_constants.KEY_ACTION]
        kwargs = mgmt_kwargs[mgmt_constants.KEY_KWARGS]

        operation, obj_type = method.split('_', 1)
        if obj_type == 'vip':
            obj_id = kwargs['vip']['id']
        elif obj_type == 'pool':
            obj_id = kwargs['pool']['id']
        elif obj_type == 'member':
            obj_id = kwargs['member']['id']
        elif obj_type == 'health_monitor':
            obj_id = {'pool_id': kwargs['pool_id'],
                      'monitor_id': kwargs['health_monitor']['id']}
        else:
            raise RuntimeError(_('unknown obj_type %s') % obj_type)

        try:
            getattr(self._driver, method)(**kwargs)
        except Exception:
            LOG.exception(_('%(operation)s %(obj)s %(id)s failed'),
                          {'operation': operation.capitalize(),
                           'obj': obj_type, 'id': obj_id})
            self.plugin_rpc.update_status(obj_type, obj_id, constants.ERROR)
        else:
            if operation in ['create', 'update']:
                self.plugin_rpc.update_status(operation, obj_id,
                                              constants.ACTIVE)

    def delete_service(self, device, service_instance, mgmt_kwargs):
        _log_debug()


# TODO(yamahata): state report agent
class ServiceInstanceAgentWithStateReport(ServiceInstanceAgent):
    pass


class ServicevmAgent(manager.Manager):
    RPC_API_VERSION = '1.0'

    def __init__(self, host, **kwargs):
        self.topic = kwargs['topic_']
        for key in ('device_uuid', 'conf'):
            setattr(self, key, kwargs[key])
        self._service_instances = {}
        device_uuid = kwargs['device_uuid']
        super(ServicevmAgent, self).__init__(host=device_uuid)

    def create(self, context, device):
        _log_debug()

    def update(self, context, device):
        _log_debug()

    def delete(self, context, device):
        _log_debug()

    def create_service(self, context, device, service_instance, mgmt_kwargs):
        service_uuid = service_instance['id']
        service_launcher = service.ServiceLauncher()
        instance_agent = ServiceInstanceAgentWithStateReport.create(
            self.conf, self.topic, device, service_instance, mgmt_kwargs)
        service_launcher.launch_service(instance_agent)
        self._service_instances[service_uuid] = service_launcher

    def update_service(self, context, device, service_instance, mgmt_kwargs):
        _log_debug()

    def delete_service(self, context, device, service_instance, mgmt_kwargs):
        service_uuid = service_instance['id']
        service_launcher = self._service_instances.pop(service_uuid)
        service_launcher.stop()
        service_launcher.wait()


def main():
    eventlet.monkey_patch()
    conf = cfg.CONF

    # import interface options just in case the driver uses namespaces
    conf.register_opts(interface.OPTS)
    config.register_agent_state_opts_helper(conf)
    config.register_root_helper(conf)
    rpc_config.register_servicevm_agent_opts(conf)

    conf(project='neutron')
    config.setup_logging(conf)
    legacy.modernize_quantum_config(conf)

    device_uuid = conf.servicevm_agent.device_id
    topic = conf.servicevm_agent.topic
    MANAGER_NAME = ('neutron.services.loadbalancer.drivers.hosting_device.'
                    'agent.agent.ServicevmAgent')
    svc = neutron_service.Service(
        host=device_uuid,
        binary='neutorn-servicevm-agent',
        topic=topic,
        topic_=topic,
        manager=MANAGER_NAME,
        device_uuid=device_uuid,
        conf=conf)
    service.launch(svc).wait()


if __name__ == '__main__':
    main()
