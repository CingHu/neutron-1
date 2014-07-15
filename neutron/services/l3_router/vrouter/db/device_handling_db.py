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

import abc
import random
import six
import uuid

from oslo.config import cfg
import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import exc

from neutron.common import constants
from neutron.db import agents_db
from neutron.db import model_base
from neutron.db import models_v2
from neutron.openstack.common import excutils
from neutron.openstack.common import log as logging
from neutron.services.l3_router.vrouter.common import stevedoreutils
from neutron.services.l3_router.vrouter.db import l3_models
from neutron.services.l3_router.vrouter.rpc import devices_cfgagent_rpc_cb
from neutron.services.l3_router.vrouter.rpc import hosting_device_rpc_agent_api


LOG = logging.getLogger(__name__)


DEVICE_HANDLING_OPTS = [
    cfg.StrOpt('device_driver',
               default=('guest_agent_device_driver'),
               help=_('Hosting device driver.')),
    cfg.StrOpt('plugging_driver',
               default=('guest_agent_plugging_driver'),
               help=_('Plugging driver for hosting device.')),
]

cfg.CONF.register_opts(DEVICE_HANDLING_OPTS, 'l3_vrouter')


class HostedHostingPortBinding(model_base.BASEV2):
    """Represents binding of logical resource's port to its hosting port."""
    # id of given resource. e.g. router_id
    logical_resource_id = sa.Column(sa.String(36), primary_key=True)

    logical_port_id = sa.Column(sa.String(36),
                                sa.ForeignKey('ports.id',
                                              ondelete="CASCADE"),
                                primary_key=True)
    logical_port = orm.relationship(
        models_v2.Port,
        primaryjoin='Port.id==HostedHostingPortBinding.logical_port_id',
        backref=orm.backref('hosting_info', cascade='all', uselist=False))
    hosting_port_id = sa.Column(sa.String(36),
                                sa.ForeignKey('ports.id',
                                              ondelete='CASCADE'))
    hosting_port = orm.relationship(
        models_v2.Port,
        primaryjoin='Port.id==HostedHostingPortBinding.hosting_port_id')

    # NetworkSegmentation in hosting port
    # See plugin.ml2.models.NetworkSegement
    network_type = sa.Column(sa.String(32), nullable=False)
    segmentation_id = sa.Column(sa.Integer, autoincrement=False)


class HostingDeviceAgentBinding(model_base.BASEV2):
    """Represents binding between hosting devices and config agents."""
    hosting_device_id = sa.Column(sa.String(36), primary_key=True)
    # complementary id to enable identification of associated Neutron resources
    # when creating port before device creation, hosting_device_id isn't
    # available.
    complementary_id = sa.Column(sa.String(36))
    mgmt_port_id = sa.Column(sa.String(36), unique=True)

    # id of config agent for this hosting device, None/NULL if unscheduled.
    agent_id = sa.Column(sa.String(36),
                         sa.ForeignKey('agents.id'), nullable=True)
    agent = orm.relationship(agents_db.Agent)
    # If 'auto_schedule' is True then router is automatically scheduled
    # if it lacks a hosting device or its hosting device fails.
    auto_schedule = sa.Column(sa.Boolean, default=True, nullable=False)


class ResourceHostingDeviceBinding(model_base.BASEV2):
    """Represents binding between resources and their hosting devices."""

    # 'L3_ROUTER_NAT', 'FIREWALL', ...
    # neutron.plugin.constants.{LOADBLANCER, FIREWALL, VPN, L3_ROUTER_NAT}
    resource_type = sa.Column(sa.String(255), nullable=False)
    reousrce_id = sa.Column(sa.String(36), primary_key=True)

    # If 'auto_schedule' is True then resource is automatically scheduled
    # if it lacks a hosting device or its hosting device fails.
    auto_schedule = sa.Column(sa.Boolean, default=True, nullable=False)

    # id of hosting device hosting this router, None/NULL if unscheduled.
    hosting_device_id = sa.Column(
        sa.String(36),
        sa.ForeignKey('hostingdeviceagentbinding.hosting_device_id'),
        nullable=True)
    agent_binding = orm.relationship(HostingDeviceAgentBinding)
    status = sa.Column(sa.String(255), nullable=False)


def _select_cfgagent(self, context, agent_binding):
    """Selects cfg agent that will configure <hosting_device>."""
    assert agent_binding.agent_id is None

    query = context.session.query(agents_db.Agent)
    cfg_agents = query.filter(
        agents_db.Agent.agent_type == constants.AGENT_TYPE_CFG,
        agents_db.Agent.admin_state_up).all()
    cfg_agents = [cfg_agent for cfg_agent in cfg_agents
                  if not agents_db.AgentDbMixin.is_agent_down(
                          cfg_agent['heartbeat_timestamp'])]
    if not cfg_agents:
        LOG.warn(_('There are no active cfg agents'))
        # No worries, once a cfg agent is started and
        # announces itself any "dangling" hosting devices
        # will be scheduled to it. register_for_duty() callback
        return
    chosen_agent = random.choice(cfg_agents)
    # agent_binding.agent_id = chosen_agent.id
    agent_binding.agent = chosen_agent


# scheduler of hosing device to cfg agent scheduler
def get_agent_host(self, context, resource_type, resource_id):
    session = context.session
    with session.begin(subtransactions=True):
        try:
            rhdb_db = (
                session.query(ResourceHostingDeviceBinding).
                filter(ResourceHostingDeviceBinding.resource_id ==
                       resource_id).
                filter(ResourceHostingDeviceBinding.resource_type ==
                       resource_type).
                one())
        except exc.NoResultFound:
            # race: someone else deleted this router
            return None
        if rhdb_db.hosting_device_id is None:
            # hosting device is not assigned to this router yet.
            return None
        agent_binding = rhdb_db.agent_binding
        if agent_binding.agnet_id is None:
            # schedule agent to hosting device
            _select_cfgagent(context, agent_binding)
            if agent_binding.agent_id is None:
                # scheduling failed
                return None

        agent = agent_binding.agent
        if not agent.admin_state_up:
            return None
        if agents_db.AgentDbMixin.is_agent_down(agent['heartbeat_timestamp']):
            return None
        return agent.host


@six.add_metaclass(abc.ABCMata)
class DeviceHandlingCallback(object):
    @abc.abstractmethod
    def handle_non_responding_hosting_devices_post(
            self, context, binding, hosting_info):
        pass

    @abc.abstractmethod
    def auto_schedule_hosting_devices(self, context, agent_host):
        pass


class DeviceHandling(object):
    """A class implementing some functionality to handle devices."""

    def __init__(self):
        super(DeviceHandling, self).__init__()
        self._hosting_device_driver = stevedoreutils.import_object(
            'neutron.services.l3_routers.vrouters.device_drivers',
            cfg.CONF.l3_vrouter.device_driver)
        self._plugging_driver = stevedoreutils.import_object(
            'neutron.services.l3_routers.vrouters.plugging_drivers',
            cfg.CONF.l3_vrouter.plugging_driver)

        notifier = hosting_device_rpc_agent_api.HostingDeviceAgentNotifierAPI()
        self._hosting_device_notifier = notifier
        self._callback = devices_cfgagent_rpc_cb.DeviceCfgRpcCallback(self)
        self._service_plugins = []

    # plugin entry point
    def register_service(self, service_plugin):
        self._service_plugins.append(service_plugin)

    # plugin entry point
    def create_resource_binding(self, context, resource_type, resource_id):
        with context.session.begin(subtransactions=True):
            rhdb_db = ResourceHostingDeviceBinding(
                resource_type=resource_type, resource_id=resource_id,
                auto_schedule=True, status=constants.PENDING_CREATE)
            context.session.add(rhdb_db)
        return rhdb_db

    # plugin entry point
    def update_resource_binding(
            self, context, resource_id, old_status, new_status,
            device_id=None):
        session = context.session
        with session.begin(subtransactions=True):
            query = (session.query(ResourceHostingDeviceBinding).
                     filter(ResourceHostingDeviceBinding.resource_id ==
                            resource_id).
                    filter(ResourceHostingDeviceBinding.status == old_status).
                    one())
            query.update({'status': new_status})
            if device_id is not None:
                query.update({'hosting_device_id': device_id})

    # plugin entry point
    def delete_resource_binding(self, context, resource_id):
        session = context.session
        with session.begin(subtransactions=True):
            (session.query(ResourceHostingDeviceBinding).
             filter(ResourceHostingDeviceBinding.resource_id == resource_id).
             filter(ResourceHostingDeviceBinding.status ==
                    constants.PENDING_DELETE).delete())

    def _invoke_plugins(self, method_name, *args):
        for plugin in self._service_plugins:
            method = getattr(plugin, method_name, None)
            if method is not None:
                method(*args)

    def _create_vm_hosting_device(self, driver_context):
        """Creates a VM instance."""

        # Note(bobmel): Nova does not handle VM dispatching well before all
        # its services have started. This creates problems for the Neutron
        # devstack script that creates a Neutron router, which in turn
        # triggers service VM dispatching.
        # Only perform pool maintenance if needed Nova services have started
        if cfg.CONF.general.ensure_nova_running and not self._nova_running:
            if self._svc_vm_mgr.nova_services_up():
                self._nova_running = True
            else:
                LOG.info(_('Not all Nova services are up and running. '
                           'Skipping this CSR1kv vm create request.'))
                return

        plugging_driver = self._plugging_driver
        hosting_device_driver = self._hosting_device_driver

        complementary_id = str(uuid.uuid4())
        dev_data = hosting_device_driver.get_plugging_data(driver_context)
        res = plugging_driver.create_hosting_device_resources(
            driver_context, complementary_id, dev_data)
        try:
            hosting_device_id = hosting_device_driver.create_device(
                driver_context, complementary_id, **res)
        except Exception:
            with excutils.save_and_reraise_exception():
                plugging_driver.delete_hosting_device_resource(
                    driver_context, None, **res)

        session = driver_context.context.session
        with session.begin(subtransactions=True):
            with session.begin(subtransactions=True):
                binding = HostingDeviceAgentBinding(
                    hosting_device_id=hosting_device_id,
                    complementary_id=complementary_id,
                    mgmt_port_id=res.get('mgmt_port_id'),
                    mgmt_url=res.get('mgmt_url'))
                session.add(binding)
        LOG.info(_('Created a hosting device VM'))
        return hosting_device_id

    def _delete_vm_hosting_device(self, driver_context, hosting_device_id):
        """Deletes a <hosting_device> service VM.

        This will indirectly make all of its hosted resources unscheduled.
        """
        context = driver_context.context
        plugging_driver = self._plugging_driver
        binding_db = (context.session.query(HostingDeviceAgentBinding).
            filter_by(hosting_device_id=hosting_device_id).one())
        res = plugging_driver.get_hosting_device_resources(
            context, hosting_device_id, binding_db['complementary_id'])

        self._hosting_device_driver.delete_device(context, binding_db)

        plugging_driver.delete_hosting_device_resources(
            driver_context, hosting_device_id, **res)

    # plugin entry point
    def schedule_service_on_hosing_device(
            self, driver_context, resource_type, resource_id):
        LOG.info(_('Attempting to schedule resource '
                   '%(resource_type)s %(resource_id)s.'),
                 {'resource_type': resource_type,
                  'resource_id': resource_id})
        device_id = self._create_vm_hosting_device(driver_context)
        return device_id

    # plugin entry point
    def unschedule_service_from_hosting_device(self, driver_context,
                                               resource_id):
        session = driver_context.context.session
        with session.begin(subtransactions=True):
            query = session.query(ResourceHostingDeviceBinding)
            resource_binding = query.filter(
                ResourceHostingDeviceBinding.resource_id == resource_id).one()
            device_id = resource_binding.hosting_device_id
        self._delete_vm_hosting_device(driver_context, device_id)

    # plugin entry point
    def setup_logical_port_connectivity(self, driver_context,
                                        port_db, hosting_device_id):
        self._plugging_driver.setup_logical_port_connectivity(
            driver_context, port_db, hosting_device_id)

    # plugin entry point
    def teardown_logical_port_connectivity(self, driver_context, port_db):
        self._plugging_driver.teardown_logical_port_connectivity(
            driver_context, port_db)

    # plugin entry point
    def extend_hosting_port_info(self, driver_context, port_db, hosting_info):
        self._plugging_driver.extend_hosting_port_info(
            driver_context, port_db, hosting_info)

    # plugin entry point
    def allocate_hosting_port(self, driver_context, resource_id,
                              port_db, hosting_device_id):
        alloc = self._plugging_driver.allocate_hosting_port(
            driver_context, resource_id, port_db, hosting_device_id)
        session = driver_context.context.session
        with session.begin(subtransactions=True):
            h_info = l3_models.HostedHostingPortBinding(
                logical_resource_id=resource_id,
                logical_port_id=port_db['id'],
                hosting_port_id=alloc['allocated_port_id'],
                network_type=alloc['network_type'],
                segmentation_id=alloc['segmentation_id'])
            session.add(h_info)
            # session.expire(port_db) # why is this needed?
        return h_info

    # callback entry point
    def handle_non_responding_hosting_devices(self, context, host,
                                              hosting_device_ids):
        with context.session.begin(subtransactions=True):
            e_context = context.elevated()
            bindings = (e_context.session.query(HostingDeviceAgentBinding).
                options(orm.joinedload('agent')).
                filter(l3_models.HostingDevice.id.in_(hosting_device_ids)).
                all())

            # 'hosting_info' is dictionary with ids of removed hosting
            # devices and the affected logical resources for each
            # removed hosting device:
            #    {'hd_id1': {'routers': [id1, id2, ...],
            #                'fw': [id1, ...],
            #                 ...},
            #     'hd_id2': {'routers': [id3, id4, ...]},
            #                'fw': [id1, ...],
            #                ...},
            #     ...}
            hosting_info = dict((id_, {}) for id_ in hosting_device_ids)
            self._invoke_plugins('_handle_non_responding_hosting_devices_db',
                                 context, bindings, hosting_info)

        self._invoke_plugins('handle_non_responding_hosting_devices_post',
                             context, bindings, hosting_info)
        for binding in bindings:
            self._delete_vm_hosting_device(context, binding.hosting_device_id)
        self._hosting_device_notifier.hosting_devices_removed(
            context, hosting_info, False, host)

    # callback entry point on agent start up via register_for_duty callback
    # scheduler of hosing device to cfg agent scheduler
    def auto_schedule_hosting_devices(self, context, agent_host):
        """Schedules unassociated hosting devices to cfg agent.

        Schedules hosting devices to agent running on <agent_host>.
        """
        session = context.session
        with session.begin(subtransactions=True):
            # Check if there is a valid cfg agent on the host
            query = session.query(agents_db.Agent)
            query = query.filter_by(agent_type=constants.AGENT_TYPE_CFG,
                                    host=agent_host, admin_state_up=True)
            try:
                cfg_agent = query.one()
            except (exc.MultipleResultsFound, exc.NoResultFound):
                LOG.debug('No enabled cfg agent on host %s', agent_host)
                return False
            if agents_db.AgetnDbMixin.is_agent_down(
                    cfg_agent['heartbeat_timestamp']):
                LOG.warn(_('cfg agent %s is not alive'), cfg_agent.id)
            query = session.query(HostingDeviceAgentBinding)
            query = query.filter_by(agent_id=None, auto_schedule=True)
            for hd in query:
                hd.cfg_agent = cfg_agent
                session.add(hd)
            return True
