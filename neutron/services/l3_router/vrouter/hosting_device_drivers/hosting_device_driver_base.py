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

import abc
import six


@six.add_metaclass(abc.ABCMeta)
class HostingDeviceDriverBase(object):
    """This class defines the API for hosting device drivers.

    These are used by servicevm plugin to perform
    various (plugin independent) operations on hosting devices.
    """

    @abc.abstractmethod
    def hosting_device_name(self):
        pass

    @abc.abstractmethod
    def get_plugging_data(self, driver_context):
        pass

    @abc.abstractmethod
    def create_device(self, driver_context):
        pass

    @abc.abstractmethod
    def delete_device(self, driver_context, binding_db):
        pass

    @abc.abstractmethod
    def get_device_info_for_agent(self, driver_context):
        """Returns information about <hosting_device> needed by config agent.

            Convenience function that service plugins can use to populate
            their resources with information about the device hosting their
            logical resource.
        """
        pass
