import requests
from kazoo.client import KazooClient
from kazoo.recipe.watchers import DataWatch, ChildrenWatch
from kazoo.protocol.states import EventType

from superwiser.common.log import logger
from superwiser.common.path import PathMaker
from superwiser.common.parser import manipulate_numprocs, build_conf
from superwiser.common.parser import parse_content, unparse
from superwiser.common.parser import extract_prog_tuples, extract_programs
from superwiser.master.distribute import distribute_work


class EyeOfMordor(object):
    def __init__(self, host, port, auto_redistribute, node_drop_callbacks):
        self.zk = KazooClient('{}:{}'.format(host, port))
        self.path = PathMaker()
        self.auto_redistribute = auto_redistribute
        self.node_drop_callbacks = node_drop_callbacks
        self.toolchains = []
        self.setup()

    def setup(self):
        logger.info('Setting up the Eye of Mordor')
        self.zk.start()
        # Setup paths
        self.setup_paths()
        # Initializse children
        self.toolchains = self.zk.get_children(self.path.toolchain())
        # Register watches
        self.register_watches()

    def setup_paths(self):
        logger.info('Setting up paths')
        self.zk.ensure_path(self.path.toolchain())
        self.zk.ensure_path(self.path.node())
        self.zk.ensure_path(self.path.baseconf())
        self.zk.ensure_path(self.path.stateconf())

    def register_watches(self):
        logger.info('Registering watches')
        DataWatch(self.zk, self.path.baseconf(), self.on_base_conf_change)
        DataWatch(self.zk, self.path.stateconf(), self.on_state_conf_change)
        ChildrenWatch(
            self.zk, self.path.toolchain(),
            self.on_toolchains, send_event=True)

    def _distribute(self, work, toolchains):
        # Distribute conf across toolchains
        assigned_work = distribute_work(work, toolchains)
        for (toolchain, awork) in assigned_work.items():
            self.zk.set(
                self.path.toolchain(toolchain),
                unparse(build_conf(awork, parse_content(work))))

    def distribute(self):
        self._distribute(
            self.get_state_conf(),
            self.zk.get_children(self.path.toolchain()))

    def on_base_conf_change(self, data, stat, event):
        if event and event.type == EventType.CHANGED:
            logger.info('Handling base conf change')
            state_programs = {
                name: (numprocs, weight)
                for name, numprocs, weight in extract_prog_tuples(
                        parse_content(self.get_state_conf()))}
            base_conf = parse_content(data)
            base_tuples = extract_prog_tuples(base_conf)
            # Rebuild state conf
            prog_tuples = []
            for (program_name, numprocs, weight) in base_tuples:
                tup = (program_name, )
                if program_name in state_programs:
                    tup += state_programs[program_name]
                else:
                    tup += (numprocs, weight)

                prog_tuples.append(tup)
            # Trigger distribute
            self.set_state_conf(unparse(build_conf(prog_tuples, base_conf)))

    def on_state_conf_change(self, data, stat, event):
        if event and event.type == EventType.CHANGED:
            logger.info('Handling state conf change')
            # Get toolchains
            toolchains = self.zk.get_children(self.path.toolchain())
            if toolchains:
                # Distribute work across toolchains
                self._distribute(data, toolchains)

    def on_toolchains(self, children, event):
        if not event:
            return
        added = set(children) - set(self.toolchains)
        removed = set(self.toolchains) - set(children)
        if added:
            logger.info('Toolchain joined')
            self.distribute()
        elif removed:
            logger.info('Toolchain left')
            # Hit callbacks
            for url in self.node_drop_callbacks:
                requests.post(url,
                              data={'node_count': len(children)})
            if self.auto_redistribute:
                self.distribute()
        self.toolchains = children

    def get_base_conf(self):
        logger.info('Getting base conf')
        data, _ = self.zk.get(self.path.baseconf())
        return data

    def set_base_conf(self, conf):
        logger.info('Updating base conf')
        self.zk.set(self.path.baseconf(), conf)

    def get_state_conf(self):
        logger.info('Getting state conf')
        data, _ = self.zk.get(self.path.stateconf())
        return data

    def set_state_conf(self, conf):
        logger.info('Updating state conf')
        self.zk.set(self.path.stateconf(), conf)

    def teardown(self):
        logger.info('Tearing down the eye of Mordor!')
        self.zk.stop()
        self.zk.close()

    def list_orcs(self):
        return self.zk.get_children(self.path.toolchain())

    def get_orc_ip(self, orc):
        return self.zk.get(self.path.node(orc))[0]

    def list_processes_for_orc(self, orc):
        return extract_prog_tuples(
            parse_content(self.zk.get(self.path.toolchain(orc))[0]))

    def list_processes(self):
        return extract_programs(parse_content(self.get_state_conf()))

    def get_stopped_processes(self):
        base_tups = extract_prog_tuples(
            parse_content(self.get_base_conf()))
        state_tups = extract_prog_tuples(
            parse_content(self.get_state_conf()))
        base_progs = set(ele[0] for ele in base_tups)
        state_progs = set(ele[0] for ele in state_tups)
        stopped_progs = (base_progs - state_progs)
        base_conf = extract_programs(parse_content(self.get_base_conf()))
        out = []
        for (name, body) in base_conf.items():
            if name in stopped_progs:
                body['name'] = name
                out.append(body)
        return out


class Sauron(object):
    def __init__(self, eye, conf=None):
        self.eye = eye
        self.conf = conf
        self.setup()

    def setup(self):
        logger.info('Setting up Sauron')
        # Override previous state of conf
        if self.conf is not None:
            # Note: this will trigger a distribute
            self.eye.set_base_conf(self.conf)
        else:
            # Trigger a distribute anyway
            self.eye.distribute()

    def increase_procs(self, program_name, factor=1):
        logger.info('Increasing procs')

        def adder(x):
            return x + factor

        new_conf = manipulate_numprocs(
            parse_content(self.eye.get_state_conf()),
            program_name,
            adder)
        # Simply set the conf to trigger a distribute and sync
        self.eye.set_state_conf(new_conf)

        return True

    def decrease_procs(self, program_name, factor=1):
        logger.info('Decreasing procs')

        def subtractor(x):
            return x - factor

        new_conf = manipulate_numprocs(
            parse_content(self.eye.get_state_conf()),
            program_name,
            subtractor)
        # Simply set the conf to trigger a distribute and sync
        self.eye.set_state_conf(new_conf)

        return True

    def start_program(self, program_name):
        prog_tuples = extract_prog_tuples(
            parse_content(self.eye.get_state_conf()))
        has_program = any(ele for ele in prog_tuples
                          if ele[0] == program_name)
        if has_program:
            logger.info('Already contains program')
            return False
        base_conf_tuples = extract_prog_tuples(
            parse_content(self.eye.get_base_conf()))
        try:
            program_tuple = next(ele for ele in base_conf_tuples
                                 if ele[0] == program_name)
        except StopIteration:
            logger.info('Program does not exist')
            return False
        # Program did not exist, let's add it now
        # Note: We set numprocs to one while adding
        prog_tuples.append(program_tuple)
        # Update conf and distribute
        self.eye.set_state_conf(
            unparse(
                build_conf(
                    prog_tuples,
                    parse_content(self.eye.get_base_conf()))))
        return True

    def stop_program(self, program_name):
        logger.info('Stopping program')
        conf = parse_content(self.eye.get_state_conf())
        # Check if program exists
        prog_tuples = extract_prog_tuples(conf)
        for (pos, (prog_name, _, _)) in enumerate(prog_tuples):
            if prog_name == program_name:
                del prog_tuples[pos]
                break
        else:
            logger.info('Program is either already stopped/not defined')
            return False
        self.eye.set_state_conf(
            unparse(
                build_conf(
                    prog_tuples,
                    conf)))
        return True

    def restart_program(self, program_name):
        self.stop_program(program_name)
        return self.start_program(program_name)

    def teardown(self):
        logger.info('Tearing down Sauron')
        self.eye.teardown()


class SauronFactory(object):
    _instance = None

    def make_sauron(self, **kwargs):
        inst = SauronFactory._instance
        if inst is None:
            logger.info('Making Sauron')

            zk_host = kwargs['zookeeper_host']
            zk_port = kwargs['zookeeper_port']
            auto_redistribute = kwargs['auto_redistribute_on_failure']
            node_drop_callbacks = kwargs['node_drop_callbacks']
            supervisor_conf = kwargs['supervisor_conf']

            if supervisor_conf is not None:
                supervisor_conf = self.read_conf(supervisor_conf)

            inst = Sauron(
                EyeOfMordor(
                    host=zk_host,
                    port=zk_port,
                    auto_redistribute=auto_redistribute,
                    node_drop_callbacks=node_drop_callbacks),
                supervisor_conf)

            SauronFactory._instance = inst

        return inst

    def read_conf(self, path):
        logger.info('Reading conf')
        with open(path) as source:
            return source.read()
