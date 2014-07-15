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
# @author: Hareesh Puthalath, Cisco Systems, Inc.
# @author: Bob Melander, Cisco Systems, Inc.


from novaclient import exceptions as nova_exc
from novaclient.v1_1 import client

from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def nova_services_up(user=None, passwd=None, l3_admin_tenant=None,
                     auth_url=''):
    """Checks if required Nova services are up and running.

    returns: True if all needed Nova services are up, False otherwise
    """
    nclient = client.Client(user, passwd, l3_admin_tenant, auth_url,
                            service_type="compute")

    try:
        services = nclient.services.list()
    # There are several individual Nova client exceptions but they have
    # no other common base than Exception, hence the long list.
    except (nova_exc.UnsupportedVersion, nova_exc.CommandError,
            nova_exc.AuthorizationFailure, nova_exc.NoUniqueMatch,
            nova_exc.AuthSystemNotFound, nova_exc.NoTokenLookupException,
            nova_exc.EndpointNotFound, nova_exc.AmbiguousEndpoints,
            nova_exc.ConnectionRefused, nova_exc.ClientException,
            Exception) as e:
        LOG.error(_('Failure determining running Nova services: %s'), e)
        return False

    required = set(['nova-conductor', 'nova-cert', 'nova-scheduler',
                    'nova-compute', 'nova-consoleauth'])
    required = required.difference(
        [service.binary for service in services
         if service.status == 'enabled' and service.state == 'up'])
    return not bool(required)
