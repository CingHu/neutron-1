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

from oslo.config import cfg
from tackerclient.v1_0 import client


TACKER_CLIENT_OPTS = [
    cfg.StrOpt('url',
               default='http://127.0.0.1:8888',
               help=_('URL for connecting to tacker')),
    cfg.IntOpt('url_timeout',
               default=30,
               help=_('Timeout value for connecting to neutron in seconds')),
    cfg.BoolOpt('api_insecure',
                default=False,
                help=_('If set, ignore any SSL validation issues')),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               help=_('Authorization strategy for connecting to '
                      'neutron in admin context')),
    cfg.StrOpt('ca_certificates_file',
               help=_('Location of CA certificates file to use for '
                      'neutron client requests.')),

    cfg.StrOpt('admin_user_id',
               help='User id for connecting to tacker in admin context'),
    cfg.StrOpt('admin_username',
               help='Username for connecting to tacker in admin context'),
    cfg.StrOpt('admin_password',
               help='Password for connecting to tacker in admin context',
               secret=True),
    cfg.StrOpt('admin_tenant_id',
               help='Tenant id for connecting to tacker in admin context'),
    cfg.StrOpt('admin_tenant_name',
               help='Tenant name for connecting to tacker in admin context. '
                    'This option will be ignored if tacker_admin_tenant_id '
                    'is set. Note that with Keystone V3 tenant names are '
                    'only unique within a domain.'),
    cfg.StrOpt('admin_auth_url',
               default='http://localhost:5000/v2.0',
               help='Authorization URL for connecting to tacker in admin '
               'context'),
]


cfg.CONF.register_opts(TACKER_CLIENT_OPTS, 'tacker')


def _get_client(token=None, admin=False):
    conf = cfg.CONF.tacker
    params = {
        'endpoint_url': conf.url,
        'timeout': conf.url_timeout,
        'insecure': conf.api_insecure,
        'ca_cert': conf.ca_certificates_file,
        'auth_strategy': conf.auth_strategy,
        'token': token,
    }

    if admin:
        if conf.admin_user_id:
            params['user_id'] = conf.admin_user_id
        else:
            params['username'] = conf.admin_username
        if conf.admin_tenant_id:
            params['tenant_id'] = conf.admin_tenant_id
        else:
            params['tenant_name'] = conf.admin_tenant_name
        params['password'] = conf.admin_password

        auth_url = (cfg.CONF.keystone_authtoken.auth_protocol + "://" +
                    cfg.CONF.keystone_authtoken.auth_host + ":" +
                    str(cfg.CONF.keystone_authtoken.auth_port) + "/v2.0")
        params['auth_url'] = auth_url
    return client.Client(**params)


def get_client(context, admin=False):
    return _get_client(context.auth_token, admin)
