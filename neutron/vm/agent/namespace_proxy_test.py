# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013, 2014 Intel Corporation.
# Copyright 2013, 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                                     <isaku.yamahata at gmail com>
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

import os
import os.path
import pickle
import socket

import eventlet
from oslo.config import cfg

from neutron.agent.common import config as agent_conf
from neutron.common import config
from neutron.common import utils
from neutron.openstack.common import log as logging
from neutron.vm.agent import config as vm_config


LOG = logging.getLogger(__name__)


_TMP = 'tmp'


class MsgHandler(object):
    def __init__(self, sock):
        self._sock = sock
        self.thread = eventlet.spawn(self._loop)

    def wait(self):
        self.thread.wait()

    def _loop(self):
        f = self._sock.makefile()
        while True:
            obj = pickle.load(f)
            print(obj)


class MsgProxy(object):
    def __init__(self, conf):
        super(MsgProxy, self).__init__()
        self.conf = conf
        if not os.path.isdir(self.conf.svcvm_proxy_dir):
            os.makedirs(self.conf.svcvm_proxy_dir)
        self._sockets = {}
        self._handlers = {}

    def run(self):
        path = os.path.join(self.conf.svcvm_proxy_dir, _TMP)
        print(path)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(path)
        handler = MsgHandler(s)
        self._sockets[_TMP] = s
        self._handlers[_TMP] = handler
        handler.wait()


def main():
    eventlet.monkey_patch()
    conf = cfg.CONF
    agent_conf.register_agent_state_opts_helper(conf)
    conf.register_opts(vm_config.OPTS)
    conf(project='neutron')
    config.setup_logging(conf)
    utils.log_opt_values(LOG)
    proxy = MsgProxy(cfg.CONF)
    proxy.run()


if __name__ == '__main__':
    main()
