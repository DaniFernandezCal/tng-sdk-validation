#  Copyright (c) 2018 SONATA-NFV, 5GTANGO, UBIWHERE, QUOBIS SL.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Neither the name of the SONATA-NFV, 5GTANGO, UBIWHERE, QUOBIS
# nor the names of its contributors may be used to endorse or promote
# products derived from this software without specific prior written
# permission.
#
# This work has been performed in the framework of the SONATA project,
# funded by the European Commission under Grant number 671517 through
# the Horizon 2020 and 5G-PPP programmes. The authors would like to
# acknowledge the contributions of their colleagues of the SONATA
# partner consortium (www.sonata-nfv.eu).
#
# This work has also been performed in the framework of the 5GTANGO project,
# funded by the European Commission under Grant number 761493 through
# the Horizon 2020 and 5G-PPP programmes. The authors would like to
# acknowledge the contributions of their colleagues of the SONATA
# partner consortium (www.5gtango.eu).

# Python packages imports
import logging
import os
import uuid
# from .event import *
import coloredlogs
import networkx as nx
import zipfile
import time
import shutil
import atexit
import errno
import yaml
import inspect
# Sonata and 55GTANGO imports
from tngsdk.project.workspace import Workspace
from tngsdk.project.project import Project
from tngsdk.validation.storage import DescriptorStorage, Test_parameter, Test_execution
# from storage import DescriptorStorage
# from son.validate.util import read_descriptor_files, list_files
# from son.validate.util import strip_root, build_descriptor_id
# from util import read_descriptor_files, list_files, strip_root
# from util import build_descriptor_id
from tngsdk.validation.util import read_descriptor_files, list_files
from tngsdk.validation.util import strip_root, build_descriptor_id
from tngsdk.validation.schema.validator import SchemaValidator
from tngsdk.validation import event
from tngsdk.validation.custom_rules import validator_custom_rules


# LOG = logging.getLogger(os.path.basename(__file__))
log = logging.getLogger(__name__)
evtlog = event.get_logger('validator.events')


class Validator(object):
    def __init__(self, workspace=None):

        # by default all the tests are performed
        self._workspace = workspace
        self._syntax = True
        self._integrity = True
        self._topology = True
        self._custom = False

        # Variable to delete, only to check custom rules errors
        self._customErrors = []
        # create "virtual" workspace if not provided (don't actually create
        # file structure)
        if not self._workspace:
            self._workspace = Workspace('.', log_level='info')
        # load configurations from workspace
        self._dext = self._workspace.default_descriptor_extension
        self._dpath = '.'
        self._log_level = self._workspace.log_level
        self._cfile = '.'
        self._workspace_path = os.path.expanduser('~/.tng-workspace/')
        # # for package signature validation
        # self._pkg_signature = None
        # self._pkg_pubkey = None
        #
        # # configure logs
        # coloredlogs.install(level=self._log_level)

        # descriptors storage
        self._storage = DescriptorStorage()

        # syntax validation
        self._schema_validator = SchemaValidator(self._workspace, preload=True)

        # reset event logger
        evtlog.reset()

        # ANTON: what's this?
        self.source_id = None
        # forwarding graphs of the NS which is going to be validated
        self._fwgraphs = dict()

        pass

    @property
    def schema_validator(self):
        return self._schema_validator
    @property
    def errors(self):
        return evtlog.errors

    @property
    def error_count(self):
        """
        Provides the number of errors given during validation.
        """
        return len(self.errors)

    @property
    def warnings(self):
        return evtlog.warnings

    @property
    def warning_count(self):
        """
        Provides the number of warnings given during validation.
        """
        return len(self.warnings)

    @property
    def storage(self):
        """
        Provides access to the stored resources during validation process.
        """
        return self._storage

    @property
    def dpath(self):
        return self._dpath

    @dpath.setter
    def dpath(self, value):
        self._dpath = value

    @property
    def customErrors(self):
        return self._customErrors

    @customErrors.setter
    def customErrors(self, value):
        self._customErrors = value

    def configure(self, syntax=None, integrity=None, topology=None,
                  custom=None, dpath=None, dext=None, debug=None,
                  cfile=None, pkg_signature=None, pkg_pubkey=None,
                  workspace_path=None):
        """
        Configure parameters for validation. It is recommended to call this
        function before performing a validation.
        :param syntax: specifies whether to validate syntax
        :param integrity: specifies whether to validate integrity
        :param topology: specifies whether to validate network topology
        :param custom: specifies whether to validate network custom rules
        :param dpath: directory to search for function descriptors (VNFDs)
        :param dext: extension of descriptor files (default: 'yml')
        :param debug: increase verbosity level of logger
        ANTON do we have to validate the signatures of the packages??
        :param pkg_signature: String package signature to be validated
        :param pkg_pubkey: String package public key to verify signature
        """
        # assign parameters
        if workspace_path is not None:
            self._workspace_path = workspace_path
        if syntax is not None:
            self._syntax = syntax
        if integrity is not None:
            self._integrity = integrity
        if topology is not None:
            self._topology = topology
        if custom is not None:
            self._custom = custom
        if dext is not None:
            self._dext = dext
        if dpath is not None:
            self._dpath = dpath
        if cfile is not None:
            self._cfile = cfile
        if debug is True:
            self._workspace.log_level = 'debug'
            coloredlogs.install(level='debug')
        if debug is False:
            self._workspace.log_level = 'info'
            coloredlogs.install(level='info')
        if pkg_signature is not None:
            self._pkg_signature = pkg_signature
        if pkg_pubkey is not None:
            self._pkg_pubkey = pkg_pubkey

    def _assert_configuration(self):
        """
        Ensures that the current configuration is compatible with the
        validation to perform. If issues are found the application is
        interrupted with the appropriate error.
        This is an internal function which must be invoked only by:
        - 'validate_package'
        - 'validate_project'
        - 'validate_service'
        - 'validate_function'
        """
        # ensure this function is called by specific functions
        caller = inspect.stack()[1][3]
        if (caller != 'validate_function' and caller != 'validate_service' and
                caller != 'validate_project' and caller != 'validate_package'):
            log.error("Cannot assert a correct configuration." +
                      " Validation scope couldn't be determined. Aborting")
            return

        # general rules - apply to all validations
        if self._integrity and not self._syntax:
            log.error("Cannot validate integrity without " +
                      "validating syntax first. Aborting.")
            return

        if self._topology and not self._integrity:
            log.error("Cannot validate topology without " +
                      "validating integrity first. Aborting.")
            return

        if self._custom and not self._topology:
            log.error("Cannot validate custom rules without " +
                      "validating topology first. Aborting.")

        if not self._syntax:
            log.error("Nothing to validate. Aborting.")
            return

        if caller == 'validate_package':
            pass
        elif caller == 'validate_project':
            pass
        elif caller == 'validate_service':
            # check SERVICE validation parameters
            if ((self._integrity or self._topology) and not
                    (self._dpath and self._dext)):
                log.error("Invalid validation parameters. To validate the "
                          "integrity, topology or custom rules of a service descriptors "
                          "both' --dpath' and '--dext' parameters must be "
                          "specified.")
                return
            if ((self._custom) and not
                    (self._dpath and self._dext and self._cfile)):
                log.error("Invalid validation parameters. To validate the "
                          "custom rules of a service descriptors"
                          "both' --dpath' and '--dext' parameters must be "
                          "specified (to validate the topology/integrity) and "
                          "'--cfile' must be specified")
        elif caller == 'validate_function':
            pass
        return True

    def validate_project(self, project):
        """
        Validate a SONATA project.
        By default, it performs the following validations: syntax, integrity
        and network topology.
        :param project: SONATA project
        :return: True if all validations were successful, False otherwise
        """
        if not self._assert_configuration():
            return
        if project.endswith('/'):
            project_path = project
        else:
            project_path = project + '/'
        # consider cases when project is a path
        #TODO NSD probably must be PD
        if not os.path.isdir(project):
            log.error("Incorrect path. Try again with a correct project path")
            return False
        #   CHECK: os.path.isdir(project) is cheked before
        if type(project) is not Project and os.path.isdir(project):
            if not self._workspace:
                log.error("Workspace not defined. Unable to validate project")
                return
            if self._workspace_path.endswith('/'):
                (self._workspace.config
                 ['projects_config']) = (self._workspace_path +
                                         'projects/config.yml')
            else:
                (self._workspace.config
                 ['projects_config']) = (self._workspace_path +
                                         '/projects/config.yml')
            project = Project.load_project(project, workspace=self._workspace_path, translate=False)
        if type(project) is not Project:
            return
        log.info("Validating project descriptors'{0}'".format(project.project_root))
        log.info("... syntax: {0}, integrity: {1}, topology: {2}"
                 .format(self._syntax, self._integrity, self._topology))

        # retrieve project configuration
        self._dpath = []
        vnfds_files = project.get_vnfds()
        for i in vnfds_files:
            self._dpath.append(project_path + i)
        self._dext = project.descriptor_extension
        # load all project descriptors present at source directory
        log.debug("Loading project service descriptor")
        nsd_file = Validator._load_project_service_file(project)
        # TODO some type of function 'project.get_tstd()' is necessary here
        with open(project_path+project.__descriptor_name__, 'r') as _file:
            try:
                descriptor = yaml.load(_file)
            except yaml.YAMLError as exc:
                return
        tstd_file = []
        for _file in descriptor["files"]:
            if _file["type"] == "application/vnd.5gtango.tstd":
                tstd_file.append(project_path+_file["path"])
        tstd_ok = True
        for _file in tstd_file:
            if not self.validate_test(_file):
                tstd_error = False
        ###
        if nsd_file and tstd_file:
            nsd_file = project_path + nsd_file
            return self.validate_service(nsd_file) and tstd_ok
        elif not(nsd_file) and tstd_ok:
            return tstd_ok
        else:
            nsd_file = project_path + nsd_file
            return self.validate_service(nsd_file)

    @staticmethod
    def _load_project_service_file(project):
        """
        Load descriptors from a SONATA SDK project.
        :param project: SDK project
        :return: True if successful, False otherwise
        """

        # load project service descriptor (NSD)
        nsd_files = project.get_nsds()
        if not nsd_files:
            log.warning("NSD not found. Couldn't find a service descriptor in project '{0}'".format(project.project_root))
            return False

        if len(nsd_files) > 1:
            evtlog.log("Multiple NSDs",
                       "Found multiple service descriptors in project "
                       "'{0}': {1}"
                       .format(project.project_root, nsd_files),
                       project.project_root,
                       'evt_project_service_multiple')
            return Falsetel

        return nsd_files[0]

    def validate_service(self, nsd_file):
        """
        Validate a 5GTANGO service.
        By default, it performs the following validations: syntax, integrity
        and network topology.
        :param nsd_file: service descriptor path
        :return: True if all validations were successful, False otherwise
        """
        if not self._assert_configuration():
            return
        log.info("Validating service descriptor '{0}'".format(nsd_file))
        log.info("... syntax: {0}, integrity: {1}, topology: {2}"
                 .format(self._syntax, self._integrity, self._topology))
        service = self._storage.create_service(nsd_file)
        if not service:
            evtlog.log("Invalid service descriptor",
                       "Failed to read the service descriptor of file '{}'"
                       .format(nsd_file),
                       nsd_file,
                       'evt_service_invalid_descriptor')
            return

        # validate service syntax
        if self._syntax and not self._validate_service_syntax(service):
            return

        if self._integrity and not self._validate_service_integrity(service):
            return

        if self._topology and not self._validate_service_topology(service):
            return

        return True

    def _validate_service_topology(self, service):
        """
        Validate the network topology of a service descriptor.
        :return:
        """
        log.info("Validating topology of service descriptor '{0}'".format(service.id))

        isolated_vnf = service.detect_isolated_vnfs()
        if isolated_vnf:
            evtlog.log("Invalid topology",
                       "The following VNF(s) are isolated in service descriptor {}: {}"
                       .format(service.id, isolated_vnf),
                       service.id,
                       'evt_nsd_top_topgraph_isolated_vnfd')
            return
        loops = service.detect_loops()
        if loops:
            evtlog.log("Invalid topology",
                       "The following loop(s) were found in the service descriptor {}: {}"
                       .format(service.id,loops),
                       service.id,
                       'evt_nsd_top_topgraph_loops_in_vnfd')
            return

        unnused_vnf_cps = service.detect_unnused_cps()
        if unnused_vnf_cps:
            evtlog.log("Invalid topology",
                       "The following CP(s) are unnused in service {}: {}"
                       .format(service.id, unnused_vnf_cps),
                       service.id,
                       'evt_nsd_top_topgraph_unnused_cps_vnfd')

        # build service topology graph with VNF connection points
        service.graph = service.build_topology_graph(level=1, bridges=True)
        if not service.graph:
            evtlog.log("Invalid topology",
                       "Couldn't build topology graph of service descriptor'{0}'"
                       .format(service.id),
                       service.id,
                       'evt_nsd_top_topgraph_failed')
            return

        log.debug("Built topology graph of service descriptor '{0}': {1}"
                  .format(service.id, service.graph.edges()))

        # write service graphs with different levels and options
        self.write_service_graphs(service)

        if nx.is_connected(service.graph):
            log.debug("Topology graph of service descriptor '{0}' is connected"
                      .format(service.id))
        else:
            evtlog.log("Disconnected topology",
                       "Topology graph of service descriptor '{0}' is disconnected"
                       .format(service.id),
                       service.id,
                       'evt_nsd_top_topgraph_disconnected')

        # check if forwarding graphs section is available
        if 'forwarding_graphs' not in service.content:
            evtlog.log("Forwarding graphs not available",
                       "No forwarding graphs available in service descriptor id='{0}'"
                       .format(service.id),
                       service.id,
                       'evt_nsd_top_fwgraph_unavailable')
            # don't enforce it (section not required)
            return True

        # load forwarding graphs
        if not service.load_forwarding_graphs():
            evtlog.log("Bad section: 'forwarding_graphs'",
                       "Couldn't load service descriptor forwarding graphs. ",
                       service.id,
                       'evt_nsd_top_badsection_fwgraph')
            return

        # analyse forwarding paths
        for fw_graph in service.fw_graphs:
            source_id = service.id + ":" + fw_graph['fg_id']

            for fw_path in fw_graph['fw_paths']:

                evtid = event.generate_evt_id()

                # check if number of connection points is odd
                if len(fw_path['path']) % 2 != 0:
                    evtlog.log("Odd number of connection points",
                               "The forwarding path fg_id='{0}', fp_id='{1}' "
                               "has an odd number of connection points".
                               format(fw_graph['fg_id'], fw_path['fp_id']),
                               source_id,
                               'evt_nsd_top_fwgraph_cpoints_odd',
                               event_id=evtid,
                               detail_event_id=fw_path['fp_id'])
                    fw_path['event_id'] = evtid

                fw_path['trace'] = service.trace_path_pairs(fw_path['path'])

                if any(pair['break'] is True for pair in fw_path['trace']):
                    evtlog.log("Invalid forwarding path ({0} breakpoint(s))"
                               .format(sum(pair['break'] is True
                                           for pair in fw_path['trace'])),
                               "fp_id='{0}':\n{1}"
                               .format(fw_path['fp_id'],
                                       yaml.dump(
                                           service.trace_path(
                                               fw_path['path']))),
                               source_id,
                               'evt_nsd_top_fwpath_invalid',
                               event_id=evtid,
                               detail_event_id=fw_path['fp_id'])
                    fw_path['event_id'] = evtid

                    # skip further analysis
                    return

                log.debug("Forwarding path fg_id='{0}', fp_id='{1}': {2}"
                          .format(fw_graph['fg_id'], fw_path['fp_id'],
                                  fw_path['trace']))

            # cycles must be analysed at the vnf level, not cp level.
            # here, a directed graph between vnfs must be created,
            # containing the cps of each node and edges between nodes.
            # Each edge must contain the pair of cps that links the
            # two nodes.
            # Having this structure is possible to find cycles between vnfs
            # and more importantly, identify which are the links
            #  (cp pair) that integrate a particular cycle.

            fpg = nx.DiGraph()
            for fw_path in fw_graph['fw_paths']:
                prev_node = None
                prev_iface = None
                pair_complete = False

                # convert 'connection point' path into vnf path
                for cp in fw_path['path']:
                    # find vnf_id of connection point
                    func = None
                    s_cp = cp.split(':')
                    if len(s_cp) == 2:
                        func = service.mapped_function(s_cp[0])
                        if not func:
                            log.error(
                                "Internal error: couldn't find corresponding"
                                " VNFs in forwarding path '{}'"
                                .format(fw_path['fp_id']))
                            return
                        node = service.vnf_id(func)

                    else:
                        node = cp
                        fpg.add_node(node)

                    if pair_complete:
                        if prev_node and prev_node == node:
                            evtid = event.generate_evt_id()
                            evtlog.log("Path within the same VNF",
                                       "The forwarding path fg_id='{0}', "
                                       "fp_id='{1}' contains a path within the"
                                       " same VNF id='{2}'"
                                       .format(fw_graph['fg_id'],
                                               fw_path['fp_id'],
                                               node),
                                       source_id,
                                       'evt_nsd_top_fwpath_inside_vnf',
                                       event_id=evtid,
                                       detail_event_id=fw_path['fp_id'])
                            fw_path['event_id'] = evtid

                            # reset trace
                            fw_path['trace'] = []
                            continue

                        fpg.add_edge(prev_node, node,
                                     attr_dict={'from': prev_iface,
                                                'to': cp})
                        pair_complete = False

                    else:
                        if prev_node and prev_node != node:
                            evtlog.log("Disrupted forwarding path",
                                       "The forwarding path fg_id='{0}', "
                                       "fp_id='{1}' is disrupted at the "
                                       "connection point: '{2}'"
                                       .format(fw_graph['fg_id'],
                                               fw_path['fp_id'],
                                               cp),
                                       source_id,
                                       'evt_nsd_top_fwpath_disrupted',
                                       event_id=source_id)

                        pair_complete = True

                    prev_node = node
                    prev_iface = cp

                # remove 'path' from fw_path (not needed anymore)
                fw_path.pop('path')

            # find cycles
            complete_cycles = list(nx.simple_cycles(fpg))

            # remove 1-hop cycles
            cycles = []
            for cycle in complete_cycles:
                if len(cycle) > 2:
                    cycles.append(cycle)

            # build cycles representative connection point structure
            cycles_list = []
            for cycle in cycles:
                cycle_dict = {'cycle_id': str(uuid.uuid4()), 'cycle_path': []}

                for idx, node in enumerate(cycle):
                    link = {}

                    if idx+1 == len(cycle):  # at last element
                        next_node = cycle[0]
                    else:
                        next_node = cycle[idx+1]

                    neighbours = fpg.neighbors(node)
                    if next_node not in neighbours:
                        log.error("Internal error: couldn't find next hop "
                                  "when building structure of cycle: {}"
                                  .format(cycle))
                        continue

                    edge_data = fpg.get_edge_data(node, next_node)
                    link['from'] = edge_data['from']
                    link['to'] = edge_data['to']

                    cycle_dict['cycle_path'].append(link)
                cycles_list.append(cycle_dict)

            # report cycles
            if cycles_list and len(cycles_list) > 0:
                evtid = event.generate_evt_id()
                for cycle in cycles_list:
                    evtlog.log("Found {0} cycle(s) (fg_id='{1}')"
                               .format(len(cycles_list), fw_graph['fg_id']),
                               "{0}"
                               .format(yaml.dump(cycle['cycle_path'],
                                       default_flow_style=False)),
                               source_id,
                               'evt_nsd_top_fwgraph_cycles',
                               event_id=evtid,
                               detail_event_id=cycle['cycle_id'])
                fw_graph['cycles'] = cycles_list
                fw_graph['event_id'] = evtid

        return True

    @staticmethod
    def write_service_graphs(service):
        graphsdir = '/tmp/graphs'
        #CHECK: Graphs isn't eliminated in different executions. Graph folder is always the same.
        try:
            os.makedirs(graphsdir)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(graphsdir):
                pass

        service.build_topology_graph(level=3, bridges=False)

        for lvl in range(0, 4):
            g = service.build_topology_graph(level=lvl, bridges=False)
            nx.write_graphml(g, os.path.join(graphsdir,
                                             "{0}-lvl{1}.graphml"
                                             .format(service.id, lvl)))
            g = service.build_topology_graph(level=lvl, bridges=True)
            nx.write_graphml(g, os.path.join(graphsdir,
                                             "{0}-lvl{1}-br.graphml"
                                             .format(service.id, lvl)))

        g = service.build_topology_graph(level=3, bridges=True,
                                         vdu_inner_connections=False)
        service.complete_graph = nx.generate_graphml(g, encoding='utf-8',
                                                     prettyprint=True)
        nx.write_graphml(g, os.path.join(graphsdir,
                                         "{0}-lvl3-complete.graphml"
                                         .format(service.id)))

    def _validate_service_syntax(self, service):
        """
        Validate a the syntax of a service (NS) against its schema.
        :param service: service to validate
        :return: True if syntax is correct, None otherwise
        """
        log.info("Validating syntax of service descriptor'{0}'".format(service.id))
        if not self._schema_validator.validate(
              service.content, SchemaValidator.SCHEMA_SERVICE_DESCRIPTOR):
            evtlog.log("Invalid NSD syntax",
                       "Invalid syntax in service descriptor'{0}': {1}"
                       .format(service.id, self._schema_validator.error_msg),
                       service.id,
                       'evt_nsd_stx_invalid')
            return
        return True

    def _validate_service_integrity(self, service):
        """
        Validate the integrity of a service (NS).
        It checks for inconsistencies in the identifiers of connection
        points, virtual links, etc.
        :param service: service to validate
        :return: True if integrity is correct
        :param service:
        :return:
        """

        log.info("Validating integrity of service descriptor '{0}'".format(service.id))
        # get referenced function descriptors (VNFDs)
        if not self._load_service_functions(service):
            evtlog.log("Function not available",
                       "Failed to read service function descriptors",
                       service.id,
                       'evt_nsd_itg_function_unavailable')
            return

        # validate service function descriptors (VNFDs)
        for fid, f in service.functions.items():
            if not self.validate_function(f.filename):
                evtlog.log("Invalid function descriptor",
                           "Failed to validate function descriptor '{0}'"
                           .format(f.filename),
                           service.id,
                           'evt_nsd_itg_function_invalid')
                return
        # load service connection points
        if not service.load_connection_points():
            evtlog.log("Bad section 'connection_points'",
                       "Couldn't load the connection points of "
                       "service descriptor id='{0}'"
                       .format(service.id),
                       service.id,
                       'evt_nsd_itg_badsection_cpoints')
            return
        # load service links
        if not service.load_virtual_links():
            evtlog.log("Bad section 'virtual_links'",
                       "Couldn't load virtual links of service descriptor id='{0}'"
                       .format(service.id),
                       service.id,
                       'evt_nsd_itg_badsection_vlinks')
            return
        undeclared = service.undeclared_connection_points()
        if undeclared:
            for cxpoint in undeclared:
                evtlog.log("{0} Undeclared connection point(s)"
                           .format(len(undeclared)),
                           "Virtual links section has undeclared connection "
                           "point: {0}".format(cxpoint),
                           service.id,
                           'evt_nsd_itg_undeclared_cpoint')
            return
        # check for unused connection points
        unused_ifaces = service.unused_connection_points()
        if unused_ifaces:
            for cxpoint in unused_ifaces:
                evtlog.log("{0} Unused connection point(s)"
                           .format(len(unused_ifaces)),
                           "Unused connection point: {0}"
                           .format(cxpoint),
                           service.id,
                           'evt_nsd_itg_unused_cpoint')

        # verify integrity between vnf_ids and vlinks
        for vl_id, vl in service.vlinks.items():
            for cpr in vl.connection_point_refs:
                s_cpr = cpr.split(':')
                if len(s_cpr) == 1 and cpr not in service.connection_points:
                    evtlog.log("Undefined connection point",
                               "Connection point '{0}' in virtual link "
                               "'{1}' is not defined"
                               .format(cpr, vl_id),
                               service.id,
                               'evt_nsd_itg_undefined_cpoint')
                    return
                elif len(s_cpr) == 2:
                    func = service.mapped_function(s_cpr[0])
                    if not func or s_cpr[1] not in func.connection_points:
                        evtlog.log("Undefined connection point",
                                   "Function descriptor (VNFD) of vnf_id='{0}' declared "
                                   "in connection point '{0}' in virtual link "
                                   "'{1}' is not defined"
                                   .format(s_cpr[0], s_cpr[1], vl_id),
                                   service.id,
                                   'evt_nsd_itg_undefined_cpoint')
                        return
        return True


    def _load_service_functions(self, service):
        """
        Loads and stores functions (VNFs) referenced in the specified service
        :param service: service
        :return: True if successful, None otherwise
        """

        log.debug("Loading function descriptors of the service.")
        # # get VNFD file list from provided dpath
        if not self._dpath:
            return
        if type(self._dpath) is list:
            vnfd_files = list(self._dpath)
        else:
            vnfd_files = list_files(self._dpath, self._dext)
            log.debug("Found {0} descriptors in dpath='{2}': {1}"
                      .format(len(vnfd_files), vnfd_files, self._dpath))

        # load all VNFDs
        path_vnfs = read_descriptor_files(vnfd_files)

        # check for errors
        if 'network_functions' not in service.content:
            log.error("Service descriptor doesn't have any functions. "
                      "Missing 'network_functions' section.")
            return

        functions = service.content['network_functions']
        if functions and not path_vnfs:
            evtlog.log("VNF not found",
                       "Service descriptor references VNFs but none could be found in "
                       "'{0}'. Please specify another '--dpath'"
                       .format(self._dpath),
                       service.id,
                       'evt_nsd_itg_function_unavailable')
            return

        # store function descriptors referenced in the service
        for func in functions:
            fid = build_descriptor_id(func['vnf_vendor'],
                                      func['vnf_name'],
                                      func['vnf_version'])
            if fid not in path_vnfs.keys():
                evtlog.log("VNF not found",
                           "Referenced function descriptor id='{0}' couldn't "
                           "be loaded".format(fid),
                           service.id,
                           'evt_nsd_itg_function_unavailable')
                return

            vnf_id = func['vnf_id']
            new_func = self._storage.create_function(path_vnfs[fid])

            service.associate_function(new_func, vnf_id)

        return True

    def validate_function(self, vnfd_path):
        """
        Validate one or multiple 5GTANGO functions (VNFs/CNFs).
        By default, it performs the following validations: syntax, integrity
        and network topology.
        :param function_path: function descriptor (VNFD/CNFD) filename or
                          a directory to search for functions
        :return: True if all validations were successful, False otherwise
        """
        # if not self._assert_configuration():
        #    return

        # validate multiple VNFs
        if os.path.isdir(vnfd_path):
            log.info("Validating function descriptors in path '{0}'".format(vnfd_path))
            vnfd_files = list_files(vnfd_path, self._dext)
            for vnfd_file in vnfd_files:
                log.info("Detected file {0} order validation..."
                         .format(vnfd_file))
                if not self.validate_function(vnfd_file):
                    return
            return True

        log.info("Validating function descriptor '{0}'".format(vnfd_path))
        log.info("... syntax: {0}, integrity: {1}, topology: {2},"
                 " custom: {3}"
                 .format(self._syntax, self._integrity, self._topology,
                         self._custom))

        func = self._storage.create_function(vnfd_path)
        if not func:
            evtlog.log("Invalid function descriptor",
                       "Couldn't store VNF/CNF of file '{0}'".format(vnfd_path),
                       vnfd_path,
                       'evt_function_invalid_descriptor')
            return

        if self._syntax and not self._validate_function_syntax(func):
            return True

        if self._integrity and not self._validate_function_integrity(func):
            return True

        if self._topology and not self._validate_function_topology(func):
            return True

        if self._custom:
            cr_validation = validator_custom_rules.process_rules(self._cfile,
                                                                 vnfd_path)
            if(len(cr_validation) != 0):
                for i in cr_validation:
                    self._customErrors.append({
                        "event_code": "errors_custom_rule_validation",
                        "event_id": vnfd_path,
                        "header": "Errors found in custom rule validation",
                        "level": "error",
                        "source_id": vnfd_path,
                        "detail": [
                            {
                                "detail_event_id": vnfd_path,
                                "message": i
                            }
                        ]
                    })
        return True

    def _validate_function_syntax(self, func):
        """
        Validate the syntax of a function (VNF) against its schema.
        :param func: function to validate
        :return: True if syntax is correct, None otherwise
        """
        log.info("Validating syntax of function descriptor '{0}'".format(func.id))
        if not self._schema_validator.validate(
                func.content, SchemaValidator.SCHEMA_FUNCTION_DESCRIPTOR):
            evtlog.log("Invalid VNFD syntax",
                       "Invalid syntax in function descriptor'{0}': {1}"
                       .format(func.id, self._schema_validator.error_msg),
                       func.id,
                       'evt_vnfd_stx_invalid')
            return
        return True

    def _validate_function_integrity(self, func):
        """
        Validate the integrity of a function (VNF).
        It checks for inconsistencies in the identifiers of connection
        points, virtual deployment units (VDUs), ...
        :param func: function to validate
        :return: True if integrity is correct
        """
        log.info("Validating integrity of function descriptor '{0}'"
                 .format(func.id))
        # load function connection points
        if not func.load_connection_points():
            evtlog.log("Missing 'connection_points'",
                       "Couldn't load the connection points of "
                       "function descriptor id='{0}'"
                       .format(func.id),
                       func.id,
                       'evt_vnfd_itg_badsection_cpoints')
            return

        # load units
        if not func.load_units():
            evtlog.log("Missing 'virtual_deployment_units or cloudnative_deployment_units'",
                       "Couldn't load the units of function descriptor id='{0}'"
                       .format(func.id),
                       func.id,
                       'evt_vnfd_itg_badsection_vdus')
            return
        # load connection points of units
        if not func.load_unit_connection_points():
            evtlog.log("Bad section 'connection_points'",
                       "Couldn't load VDU connection points of "
                       "function descriptor id='{0}'"
                       .format(func.id),
                       func.id,
                       'evt_vnfd_itg_vdu_badsection_cpoints')
            return

        # load function links
        if not func.load_virtual_links():
            evtlog.log("Bad section 'virtual_links'",
                       "Couldn't load the links of function descriptor id='{0}'"
                       .format(func.id),
                       func.id,
                       'evt_vnfd_itg_badsection_vlinks')
            return

        # check for undeclared connection points
        undeclared = func.undeclared_connection_points()
        if undeclared:
            for cxpoint in undeclared:
                evtlog.log("{0} Undeclared connection point(s)"
                           .format(len(undeclared)),
                           "Virtual links section has undeclared connection "
                           "points: {0}".format(cxpoint),
                           func.id,
                           'evt_vnfd_itg_undeclared_cpoint')
            return

        # check for unused connection points
        unused_ifaces = func.unused_connection_points()
        if unused_ifaces:
            for cxpoint in unused_ifaces:
                evtlog.log("{0} Unused connection point(s)"
                           .format(len(unused_ifaces)),
                           "Function descriptor has unused connection points: {0}"
                           .format(cxpoint),
                           func.id,
                           'evt_vnfd_itg_unused_cpoint')

        # verify integrity between unit connection points and units
        for vl_id, vl in func.vlinks.items():
            for cpr in vl.connection_point_refs:
                s_cpr = cpr.split(':')
                if len(s_cpr) == 1 and cpr not in func.connection_points:
                    evtlog.log("Undefined connection point",
                               "Connection point '{0}' in virtual link "
                               "'{1}' is not defined"
                               .format(cpr, vl_id),
                               func.id,
                               'evt_nsd_itg_undefined_cpoint')
                    return
                elif len(s_cpr) == 2:
                    unit = func.units[s_cpr[0]]
                    if not unit or s_cpr[1] not in unit.connection_points:

                        evtlog.log("Undefined connection point(s)",
                                   "Invalid connection point id='{0}' "
                                   "of virtual link id='{1}': Unit id='{2}' "
                                   "is not defined"
                                   .format(s_cpr[1], vl_id, s_cpr[0]),
                                   func.id,
                                   'evt_vnfd_itg_undefined_cpoint')
                        return
        #verify the port duplication (i.e) two CDU mustn't listen in the same port
        duplicated_ports = func.search_duplicate_ports()
        if duplicated_ports:
            dic_port_unit = func.get_units_by_ports(duplicated_ports)
            evtlog.log("Duplicated ports",
                       "The following CDUs have duplicated ports in function {}: {} "
                       .format(func.id,dic_port_unit),
                       func.id,
                       'evt_vnfd_itg_duplicated_ports_in_CDUs')
            return
        return True

    def _validate_function_topology(self, func):
        """
        This functions validates the network topology of a function.
        It builds the topology graph of the function, including VDU
        connections.
        :param func: function to validate
        :return: True if topology doesn't present issues
        """
        log.info("Validating topology of function descriptor '{0}'"
                 .format(func.id))
        isolated_units = func.detect_disconnected_units()
        if isolated_units:
            evtlog.log("Invalid topology graph",
                        "{} isolated units were found in the topology"
                        .format(len(isolated_units)),
                        func.id,
                        "evt_vnfd_top_isolated_units")
            return

        unnused_cps = func.detect_unnused_cps_units()
        if unnused_cps:
            evtlog.log( "Invalid toplogy graph",
                        "The following CP(s) are not used in function {}: {}".format(func.id, unnused_cps),
                        func.id,
                        "evt_vnfd_top_unnused_cps_unit")
        loops = func.detect_loops()
        if loops:
            evtlog.log("Invalid toplogy graph",
                        "{} loop(s) was/were found in the topology"
                        .format(len(loops)),
                        func.id,
                        "evt_vnfd_top_loops")
            return

        bridges = True
        func.graph = func.build_topology_graph(bridges)
        if not func.graph:
            evtlog.log("Invalid topology graph",
                       "Couldn't build topology graph of function descriptor '{0}'"
                       .format(func.id),
                       func.id,
                       'evt_vnfd_top_topgraph_failed')
            return

        log.debug("Built topology graph of function descriptor '{0}': {1}"
                  .format(func.id, func.graph.edges()))
        log.info("Built topology graph of function descriptor'{0}': {1}"
                 .format(func.id, func.graph.edges()))

        if not(bridges):
            cycles = None
            cycles = nx.cycle_basis(func.graph)
            if cycles:
                evtlog.log("Invalid topology graph",
                           "{} cycle(s) was/were found in the topology"
                           .format(len(cycles)),
                           func.id,
                           'evt_vnfd_top_cycles')
                return
        return True
    def workspace(self):
        log.warning("workspace not implemented")


    def validate_test(self, test_path):
        """
        Validate one or multiple 5GTANGO tests (TSTD).
        By default, it performs the following validations: syntax, integrity.
        :param test_path: function descriptor TSTD filename or
                          a directory to search for tests
        :return: True if all validations were successful, False otherwise
        """
        if os.path.isdir(test_path):
            log.info("Validating test descriptors in path '{0}'".format(test_path))
            test_files = list_files(test_path, self._dext)
            for test in test_files:
                log.info("Detected file {0} order validation..."
                         .format(test))
                if not self.validate_test(test):
                    return
            return True

        log.info("Validating test descriptor '{0}'".format(test_path))
        log.info("... syntax: {0}, integrity: {1}"
                 .format(self._syntax, self._integrity))

        test = self._storage.create_test(test_path)

        if not(test) or test.content is None:
            evtlog.log("Invalid test descriptor",
                       "Couldn't store TSTD of file '{0}'".format(test_path),
                       test_path,
                       'evt_test_invalid_descriptor')
            return

        if self._syntax and not self._validate_test_syntax(test):
            return

        if self._integrity and not self._validate_test_integrity(test):
            return
        return True

    def _validate_test_syntax(self, test):
        """
        Validate the syntax of a test (TSTD) against its schema.
        :param test: test to validate
        :return: True if syntax is correct, None otherwise
        """
        log.info("Validating syntax of test descriptor '{0}'".format(test.id))
        if not self._schema_validator.validate(
                test.content, SchemaValidator.SCHEMA_TEST_DESCRIPTOR):
            evtlog.log("Invalid TSTD syntax",
                       "Invalid syntax in test descriptor'{0}': {1}"
                       .format(test.id, self._schema_validator.error_msg),
                       test.id,
                       'evt_tstd_stx_invalid')
            return
        return True
    def _validate_test_integrity(self, test):
        """
        Validate the existence of all elements in the test descriptor i.e. configuration
        parameters...
        :test: test to validate
        :return: True if integrity is correct, False otherwise
        """
        log.info("Validating integrity of test descriptor '{0}'"
                 .format(test.id))

        if "test_type" not in test.content:
            evtlog.log("Missing 'test_type'",
                       "Couldn't load the test_type of "
                       "test descriptor id='{0}'"
                       .format(test.id),
                       test.id,
                       'evt_tstd_itg_badsection_test_type')
            return
        test.set_test_type(test.content["test_type"])

        if "test_category" not in test.content:
            evtlog.log("Missing 'test_category'",
                       "Couldn't load the test_category of "
                       "test descriptor id='{0}'"
                       .format(test.id),
                       test.id,
                       'evt_tstd_itg_badsection_test_category')
            return
        test.set_test_category(test.content["test_category"])

        if "test_configuration_parameters" not in test.content:
            evtlog.log("Missing 'test_configuration_parameters'",
                       "Couldn't load the test_configuration_parameters of "
                       "test descriptor id='{0}'"
                       .format(test.id),
                       test.id,
                       'evt_tstd_itg_badsection_test_configuration_parameters')
            return
        conf_params = test.content["test_configuration_parameters"]
        for param in conf_params:
            if "parameter_name" not in param:
                evtlog.log("Missing 'parameter_name' in 'test_configuration_parameters'",
                           "Couldn't load the test_configuration_parameters of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_configuration_parameters_parameter_name')
                return
            elif "parameter_definition" not in param:
                evtlog.log("Missing 'parameter_definition' in test_configuration_parameters",
                           "Couldn't load the test_configuration_parameters of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_configuration_parameters_parameter_definition')
                return
            elif "parameter_value" not in param:
                evtlog.log("Missing 'parameter_value' in 'test_configuration_parameters'",
                           "Couldn't load the test_configuration_parameters of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_configuration_parameters_parameter_value')
                return
            elif "content_type" not in param:
                evtlog.log("Missing 'content_type' in 'test_configuration_parameters'",
                           "Couldn't load the test_configuration_parameters of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_configuration_parameters_content_type')
                return
            elif len(param)>4:
                print("So many properties")
                return
            else:
                new_test_conf_param = Test_parameter(param)
                test.add_test_configuration_parameter(new_test_conf_param)

        if "test_execution" not in test.content:
            evtlog.log("Missing 'test_execution'",
                       "Couldn't load the test_execution of "
                       "test descriptor id='{0}'"
                       .format(test.id),
                       test.id,
                       'evt_tstd_itg_badsection_test_execution')
            return
        test_executions = test.content["test_execution"]
        for test_execution in test_executions:
            if "test_tag" not in test_execution:
                evtlog.log("Missing 'test_tag' in 'test_execution'",
                           "Couldn't load the test_execution of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_execution_test_tag')
                return
            elif "tag_id" not in test_execution:
                evtlog.log("Missing 'test_id' in 'test_execution'",
                           "Couldn't load the test_execution of "
                           "test descriptor id='{0}'"
                           .format(test.id),
                           test.id,
                           'evt_tstd_itg_badsection_test_execution_test_id')
                return
            else:
                new_test_execution = Test_execution(test_execution)
                test.add_test_execution(new_test_execution)
        return True
