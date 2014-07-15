# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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
# @author: Bob Melander, Cisco Systems, Inc.
# @author: Hareesh Puthalath, Cisco Systems, Inc.
# @author: Isaku Yamahata, Intel Cooperation

import abc
import six


@six.add_metaclass(abc.ABCMeta)
class PluginSidePluggingDriver(object):
    """This class defines the API for plugging drivers.

    These are used used by (routing service) plugin to perform
    various operations on the logical ports of logical (service) resources
    in a plugin compatible way.
    """

    @abc.abstractmethod
    def create_hosting_device_resources(self, driver_context, complementary_id,
                                        **kwargs):
        """Create resources for a hosting device in a plugin specific way.

        Called when a hosting device is to be created so resources like
        networks and ports can be created for it in a plugin compatible
        way. This is primarily useful to service VMs.

        returns: a dict {'mgmt_port': <mgmt port or None>,
                         'ports': <list of ports>,
                         ... arbitrary driver items }

        :param context: Neutron api request context.
        :param complementary_id: complementary id of hosting device
        """
        pass

    @abc.abstractmethod
    def get_hosting_device_resources(self, driver_context,
                                     hosting_device_id, complementary_id):
        """Returns information about all resources for a hosting device.

        Called just before a hosting device is to be deleted so that
        information about the resources the hosting device uses can be
        collected.

        returns: a dict {'mgmt_port': <mgmt port or None>,
                         'ports': <list of ports>,
                         ... arbitrary driver items }

        :param context: Neutron api request context.
        :param hosting_device_id: id of hosting device.
        :param complementary_id: complementary id of hosting device
        """
        pass

    @abc.abstractmethod
    def delete_hosting_device_resources(self, driver_context,
                                        hosting_device_id, **kwargs):
        """Deletes resources for a hosting device in a plugin specific way.

        Called when a hosting device has been deleted (or when its creation
        has failed) so resources like networks and ports can be deleted in
        a plugin compatible way. This it primarily useful to service VMs.

        :param driver_context: Neutron api request context.
        :param hosting_device_id: id of tenant owning the hosting device
                                  resources.
        :param kwargs: dictionary for any driver specific parameters.
        """
        pass

    @abc.abstractmethod
    def setup_logical_port_connectivity(self, driver_context,
                                        port_db, hosting_deivce_id):
        """Establishes connectivity for a logical port.

        Performs the configuration tasks needed in the infrastructure
        to establish connectivity for a logical port.

        :param context: Neutron api request context.
        :param port_db: Neutron port that has been created.
        :param hosting_device_id: id of hosting device.
        """
        pass

    @abc.abstractmethod
    def teardown_logical_port_connectivity(self, driver_context,
                                           port_db, hosting_device_id):
        """Removes connectivity for a logical port.

        Performs the configuration tasks needed in the infrastructure
        to disconnect a logical port.

        Example: Remove a VLAN that is trunked to a service VM.

        :param context: Neutron api request context.
        :param port_db: Neutron port about to be deleted.
        :param hosting_device_id: id of hosting device.
        """
        pass

    @abc.abstractmethod
    def extend_hosting_port_info(self, driver_context, port_db, hosting_info):
        """Extends hosting information for a logical port.

        Allows a driver to add driver specific information to the
        hosting information for a logical port.

        :param driver_context: Neutron api request context.
        :param port_db: Neutron port that hosting information concerns.
        :param hosting_info: dict with hosting port information to be extended.
        """
        pass

    @abc.abstractmethod
    def allocate_hosting_port(self, driver_context, resource_id,
                              port_db, hosting_device_id):
        """Allocates a hosting port for a logical port.

        Schedules a logical port to a hosting port. Note that the hosting port
        may be the logical port itself.

        returns: a dict {'allocated_port_id': <id of allocated port>,
                         'network_type': <FLAT, VLAN, ...>
                         'segmentation_id': <allocated segement id or None>}

        :param driver_context: Neutron api request context.
        :param router_id: id of Neutron router the logical port belongs to.
        :param port_db: Neutron logical router port.
        :param hosting_device_id: id of hosting device
        """
        pass
