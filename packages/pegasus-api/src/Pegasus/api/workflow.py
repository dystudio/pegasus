import json
from collections import OrderedDict, defaultdict
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Dict, List, Literal, Optional, TextIO, Union

from ._utils import _chained, _get_enum_str
from .errors import DuplicateError, NotFoundError, PegasusError
from .mixins import HookMixin, MetadataMixin, ProfileMixin
from .replica_catalog import File, ReplicaCatalog
from .site_catalog import SiteCatalog
from .transformation_catalog import Transformation, TransformationCatalog
from .writable import Writable, _CustomEncoder, _filter_out_nones

from Pegasus.client._client import from_env

PEGASUS_VERSION = "5.0"

__all__ = ["AbstractJob", "Job", "SubWorkflow", "Workflow"]


class AbstractJob(HookMixin, ProfileMixin, MetadataMixin):
    """An abstract representation of a workflow job"""

    def __init__(self, _id: Optional[str] = None, node_label: Optional[str] = None):
        """
        :param _id: a unique id, if None is given then one will be assigned when this job is added to a :py:class:`~Pegasus.api.workflow.Workflow`, defaults to None
        :type _id: Optional[str]
        :param node_label: a short descriptive label that can be assined to this job, defaults to None
        :type node_label: Optional[str]
        """
        self._id = _id
        self.node_label = node_label
        self.args = list()
        self.uses = set()

        self.stdout = None
        self.stderr = None
        self.stdin = None

        self.hooks = defaultdict(list)
        self.profiles = defaultdict(dict)
        self.metadata = dict()

    @_chained
    def add_inputs(self, *input_files: File, bypass_staging: bool = False):
        """
        add_inputs(self, *input_files: File, bypass: bool = False)
        Add one or more :py:class:`~Pegasus.api.replica_catalog.File` objects as input to this job

        :param input_files: the :py:class:`~Pegasus.api.replica_catalog.File` objects to be added as inputs to this job
        :param bypass_staging: whether or not to bypass the staging site when this file is fetched by the job, defaults to False
        :type bypass_staging: bool, optional
        :raises DuplicateError: all input files must be unique
        :raises TypeError: job inputs must be of type :py:class:`~Pegasus.api.replica_catalog.File`
        :return: self
        """
        for file in input_files:
            if not isinstance(file, File):
                raise TypeError(
                    "invalid input_file: {file}; input_file(s) must be of type File".format(
                        file=file
                    )
                )

            _input = _Use(
                file,
                _LinkType.INPUT,
                register_replica=None,
                stage_out=None,
                bypass_staging=bypass_staging,
            )
            if _input in self.uses:
                raise DuplicateError(
                    "file: {file} has already been added as input to this job".format(
                        file=file.lfn
                    )
                )

            self.uses.add(_input)

    def get_inputs(self):
        """Get this job's input :py:class:`~Pegasus.api.replica_catalog.File` s

        :return: all input files associated with this job
        :rtype: set
        """
        return {use.file for use in self.uses if use._type == "input"}

    @_chained
    def add_outputs(
        self, *output_files: File, stage_out: bool = True, register_replica: bool = True
    ):
        """
        add_outputs(self, *output_files: File, stage_out: bool = True, register_replica: bool = True)
        Add one or more :py:class:`~Pegasus.api.replica_catalog.File` objects as outputs to this job. :code:`stage_out` and :code:`register_replica`
        will be applied to all files given.

        :param output_files: the :py:class:`~Pegasus.api.replica_catalog.File` objects to be added as outputs to this job
        :param stage_out: whether or not to send files back to an output directory, defaults to True
        :type stage_out: bool, optional
        :param register_replica: whether or not to register replica with a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog`, defaults to True
        :type register_replica: bool, optional
        :raises DuplicateError: all output files must be unique
        :raises TypeError: a job output must be of type File
        :return: self
        """
        for file in output_files:
            if not isinstance(file, File):
                raise TypeError(
                    "invalid output_file: {file}; output_file(s) must be of type File".format(
                        file=file
                    )
                )

            output = _Use(
                file,
                _LinkType.OUTPUT,
                stage_out=stage_out,
                register_replica=register_replica,
            )
            if output in self.uses:
                raise DuplicateError(
                    "file: {file} already added as output to this job".format(
                        file=file.lfn
                    )
                )

            self.uses.add(output)

    def get_outputs(self):
        """Get this job's output :py:class:`~Pegasus.api.replica_catalog.File` objects

        :return: all output files associated with this job
        :rtype: set
        """
        return {use.file for use in self.uses if use._type == "output"}

    @_chained
    def add_checkpoint(
        self,
        checkpoint_file: File,
        stage_out: bool = True,
        register_replica: bool = True,
    ):
        """
        add_checkpoint(self, checkpoint_file: File, stage_out: bool = True, register_replica: bool = True)
        Add an output :py:class:`~Pegasus.api.replica_catalog.File` of this job as a checkpoint file

        :param checkpoint_file: the :py:class:`~Pegasus.api.replica_catalog.File` to be added as a checkpoint file to this job
        :type checkpoint_file: File
        :param stage_out: whether or not to send files back to an output directory, defaults to True
        :type stage_out: bool, optional
        :param register_replica: whether or not to register replica with a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog`, defaults to True
        :type register_replica: bool, optional
        :raises DuplicateError: all output files must be unique
        :raises TypeError: a job output must be of type File
        :return: self
        """

        if not isinstance(checkpoint_file, File):
            raise TypeError(
                "invalid checkpoint_file: {file}; checkpoint_file must be of type File".format(
                    file=checkpoint_file
                )
            )

        checkpoint = _Use(
            checkpoint_file,
            _LinkType.CHECKPOINT,
            stage_out=stage_out,
            register_replica=register_replica,
        )

        if checkpoint in self.uses:
            raise DuplicateError(
                "file: {file} already added as output to this job".format(
                    file=checkpoint_file.lfn
                )
            )

        self.uses.add(checkpoint)

    @_chained
    def add_args(self, *args: Union[File, int, float, str]):
        """
        add_args(self, *args: Union[File, int, float, str])
        Add arguments to this job. Each argument will be separated by a space.
        Each argument must be either a File, scalar, or str.

        :param args: arguments to pass to this job (each arg in arg will be separated by a space)
        :type args: Union[File, int, float, str]
        :return: self
        """
        self.args.extend(args)

    @_chained
    def set_stdin(self, file: Union[str, File]):
        """
        set_stdin(self, file: Union[str, File])
        Set stdin to a :py:class:`~Pegasus.api.replica_catalog.File` . If file
        is given as a str, a :py:class:`~Pegasus.api.replica_catalog.File` object
        is created for you internally with the given value as its lfn.

        :param file: a file that will be read into stdin
        :type file: Union[str, File]
        :raises TypeError: file must be of type :py:class:`~Pegasus.api.replica_catalog.File` or str
        :raises DuplicateError: stdin is already set or the given file has already been added as an input to this job
        :return: self
        """
        if not isinstance(file, (File, str)):
            raise TypeError(
                "invalid file: {file}; file must be of type File or str".format(
                    file=file
                )
            )

        if self.stdin is not None:
            raise DuplicateError("stdin has already been set to a file")

        if isinstance(file, str):
            file = File(file)

        self.add_inputs(file)
        self.stdin = file

    def get_stdin(self):
        """Get the :py:class:`~Pegasus.api.replica_catalog.File` being used for stdin

        :return: the stdin file
        :rtype: File
        """
        return self.stdin

    @_chained
    def set_stdout(
        self,
        file: Union[str, File],
        stage_out: bool = True,
        register_replica: bool = True,
    ):
        """
        set_stdout(self, file: Union[str, File], stage_out: bool = True, register_replica: bool  = True)
        Set stdout to a :py:class:`~Pegasus.api.replica_catalog.File` . If file is given as a str,
        a :py:class:`~Pegasus.api.replica_catalog.File` object is created for you internally
        with the given value as its lfn.

        :param file: a file that stdout will be written to
        :type file: Union[str, File]
        :param stage_out: whether or not to send files back to an output directory, defaults to True
        :type stage_out: bool, optional
        :param register_replica: whether or not to register replica with a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog`, defaults to True
        :type register_replica: bool, optional
        :raises TypeError: file must be of type :py:class:`~Pegasus.api.replica_catalog.File` or str
        :raises DuplicateError: stdout is already set or the given file has already been added as an output to this job
        :return: self
        """
        if not isinstance(file, (File, str)):
            raise TypeError(
                "invalid file: {file}; file must be of type File or str".format(
                    file=file
                )
            )

        if self.stdout is not None:
            raise DuplicateError("stdout has already been set to a file")

        if isinstance(file, str):
            file = File(file)

        self.add_outputs(file, stage_out=stage_out, register_replica=register_replica)
        self.stdout = file

    def get_stdout(self):
        """Get the :py:class:`~Pegasus.api.replica_catalog.File` being used for stdout

        :return: the stdout file
        :rtype: File
        """
        return self.stdout

    @_chained
    def set_stderr(
        self,
        file: Union[str, File],
        stage_out: bool = True,
        register_replica: bool = True,
    ):
        """
        set_stderr(self, file: Union[str, File], stage_out: bool = True, register_replica: bool = True)
        Set stderr to a :py:class:`~Pegasus.api.replica_catalog.File` . If file is given as a str,
        a :py:class:`~Pegasus.api.replica_catalog.File` object is created for you internally
        with the given value as its lfn.

        :param file: a file that stderr will be written to
        :type file: Union[str, File]
        :param stage_out: whether or not to send files back to an output directory, defaults to True
        :type stage_out: bool, optional
        :param register_replica: whether or not to register replica with a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog`, defaults to True
        :type register_replica: bool, optional
        :raises TypeError: file must be of type :py:class:`~Pegasus.api.replica_catalog.File` or str
        :raises DuplicateError: stderr is already set or the given file has already been added as an output to this job
        :return: self
        """
        if not isinstance(file, (File, str)):
            raise TypeError(
                "invalid file: {file}; file must be of type File or str".format(
                    file=file
                )
            )

        if self.stderr is not None:
            raise DuplicateError("stderr has already been set to a file")

        if isinstance(file, str):
            file = File(file)

        self.add_outputs(file, stage_out=stage_out, register_replica=register_replica)
        self.stderr = file

    def get_stderr(self):
        """Get the :py:class:`~Pegasus.api.replica_catalog.File` being used for stderr

        :return: the stderr file
        :rtype: File
        """
        return self.stderr

    def __json__(self):
        return _filter_out_nones(
            {
                "id": self._id,
                "stdin": self.stdin.lfn if self.stdin is not None else None,
                "stdout": self.stdout.lfn if self.stdout is not None else None,
                "stderr": self.stderr.lfn if self.stderr is not None else None,
                "nodeLabel": self.node_label,
                "arguments": [
                    arg.lfn if isinstance(arg, File) else arg for arg in self.args
                ],
                "uses": [use for use in self.uses],
                "profiles": dict(self.profiles) if len(self.profiles) > 0 else None,
                "metadata": self.metadata if len(self.metadata) > 0 else None,
                "hooks": {
                    hook_name: [hook for hook in values]
                    for hook_name, values in self.hooks.items()
                }
                if len(self.hooks) > 0
                else None,
            }
        )


class Job(AbstractJob):
    """
    A typical workflow Job that executes a :py:class:`~Pegasus.api.transformation_catalog.Transformation`.
    See :py:class:`~Pegasus.api.workflow.AbstractJob` for full list of available functions.

    .. code-block:: python

        # Example
        if1 = File("if1")
        if2 = File("if2")

        of1 = File("of1")
        of2 = File("of2")

        # Assuming a transformation named "analyze.py" has been added to your
        # transformation catalog:
        job = Job("analyze.py")\\
                .add_args("-i", if1, if2, "-o", of1, of2)\\
                .add_inputs(if1, if2)\\
                .add_outputs(of1, of2, stage_out=True, register_replica=False)

    """

    def __init__(
        self,
        transformation: Union[str, Transformation],
        _id: Optional[str] = None,
        node_label: Optional[str] = None,
        namespace: Optional[str] = None,
        version: Optional[str] = None,
    ):
        """
        :param transformation: :py:class:`~Pegasus.api.transformation_catalog.Transformation` object or name of the transformation that this job uses
        :type transformation: Union[str, Transformation]
        :param _id: a unique id; if none is given then one will be assigned when the job is added by a :py:class:`~Pegasus.api.workflow.Workflow`, defaults to None
        :type _id: Optional[str]
        :param node_label: a brief job description, defaults to None
        :type node_label: Optional[str]
        :param namespace: namespace to which the :py:class:`~Pegasus.api.transformation_catalog.Transformation` belongs, defaults to None
        :type namespace: Optional[str]
        :param version: version of the given :py:class:`~Pegasus.api.transformation_catalog.Transformation`, defaults to None
        :type version: Optional[str]
        :raises TypeError: transformation must be one of type :py:class:`~Pegasus.api.transformation_catalog.Transformation` or str
        """
        if isinstance(transformation, Transformation):
            self.transformation = transformation.name
            self.namespace = transformation.namespace
            self.version = transformation.version
        elif isinstance(transformation, str):
            self.transformation = transformation
            self.namespace = namespace
            self.version = version
        else:
            raise TypeError(
                "invalid transformation: {transformation}; transformation must be of type Transformation or str".format(
                    transformation=transformation
                )
            )

        AbstractJob.__init__(self, _id=_id, node_label=node_label)

    def __json__(self):
        job_json = {
            "type": "job",
            "namespace": self.namespace,
            "version": self.version,
            "name": self.transformation,
        }

        job_json.update(AbstractJob.__json__(self))

        return _filter_out_nones(job_json)


class SubWorkflow(AbstractJob):
    """
    Job that represents a subworkflow.
    See :py:class:`~Pegasus.api.workflow.AbstractJob` for full list of available functions.
    """

    def __init__(
        self,
        file: Union[str, File],
        is_planned: bool,
        _id: Optional[str] = None,
        node_label: Optional[str] = None,
    ):
        """
        :param file: :py:class:`~Pegasus.api.replica_catalog.File` object or name of the workflow file that will be used for this job
        :type file: Union[str, File]
        :param is_planned: whether or not this subworkflow has already been planned by the Pegasus planner
        :type is_planned: bool
        :param _id: a unique id; if none is given then one will be assigned when the job is added by a :py:class:`~Pegasus.api.workflow.Workflow`, defaults to None
        :type _id: Optional[str]
        :param node_label: a brief job description, defaults to None
        :type node_label: Optional[str]
        :raises TypeError: file must be of type :py:class:`~Pegasus.api.replica_catalog.File` or str
        """
        AbstractJob.__init__(self, _id=_id, node_label=node_label)

        if not isinstance(file, (File, str)):
            raise TypeError(
                "invalid file: {file}; file must be of type File or str".format(
                    file=file
                )
            )

        self.type = "condorWorkflow" if is_planned else "pegasusWorkflow"
        self.file = file if isinstance(file, File) else File(file)

        self.add_inputs(self.file)

    def __json__(self):
        dax_json = {"type": self.type, "file": self.file.lfn}
        dax_json.update(AbstractJob.__json__(self))

        return dax_json


class _LinkType(Enum):
    """Internal class defining link types"""

    INPUT = "input"
    OUTPUT = "output"
    CHECKPOINT = "checkpoint"


class _Use:
    """Internal class used to represent input and output files of a job"""

    def __init__(
        self,
        file,
        link_type,
        stage_out=True,
        register_replica=True,
        bypass_staging=False,
    ):
        if not isinstance(file, File):
            raise TypeError(
                "invalid file: {file}; file must be of type File".format(file=file)
            )

        self.file = file

        if not isinstance(link_type, _LinkType):
            raise TypeError(
                "invalid link_type: {link_type}; link_type must one of {enum_str}".format(
                    link_type=link_type, enum_str=_get_enum_str(_LinkType)
                )
            )

        if link_type != _LinkType.INPUT and bypass_staging:
            raise ValueError("bypass can only be set to True when link type is INPUT")

        self.bypass = None
        if bypass_staging:
            self.bypass = bypass_staging

        self._type = link_type.value

        self.stage_out = stage_out
        self.register_replica = register_replica

    def __hash__(self):
        return hash(self.file)

    def __eq__(self, other):
        if isinstance(other, _Use):
            return self.file.lfn == other.file.lfn
        raise ValueError("_Use cannot be compared with {}".format(type(other)))

    def __json__(self):
        return _filter_out_nones(
            {
                "lfn": self.file.lfn,
                "metadata": self.file.metadata if len(self.file.metadata) > 0 else None,
                "size": self.file.size,
                "type": self._type,
                "stageOut": self.stage_out,
                "registerReplica": self.register_replica,
                "bypass": self.bypass,
            }
        )


class _JobDependency:
    """Internal class used to represent a jobs dependencies within a workflow"""

    def __init__(self, parent_id, children_ids):
        self.parent_id = parent_id
        self.children_ids = children_ids

    def __eq__(self, other):
        if isinstance(other, _JobDependency):
            return (
                self.parent_id == other.parent_id
                and self.children_ids == other.children_ids
            )
        raise ValueError(
            "_JobDependency cannot be compared with {}".format(type(other))
        )

    def __json__(self):
        return {"id": self.parent_id, "children": list(self.children_ids)}


def _needs_client(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if not self._client:
            self._client = from_env()

        f(self, *args, **kwargs)

    return wrapper


def _needs_submit_dir(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if not self._submit_dir:
            raise PegasusError(
                "{f} requires a submit directory to be set; Workflow.plan() must be called prior to {f}".format(
                    f=f
                )
            )

        return f(self, *args, **kwargs)

    return wrapper


class Workflow(Writable, HookMixin, ProfileMixin, MetadataMixin):
    """Represents multi-step computational steps as a directed
    acyclic graph.

    .. code-block:: python

        # Example
        import logging

        from pathlib import Path

        from Pegasus.api import *

        logging.basicConfig(level=logging.DEBUG)

        # --- Replicas -----------------------------------------------------------------
        with open("f.a", "w") as f:
            f.write("This is sample input to KEG")

        fa = File("f.a").add_metadata(creator="ryan")
        rc = ReplicaCatalog().add_replica("local", fa, Path(".") / "f.a")

        # --- Transformations ----------------------------------------------------------
        preprocess = Transformation(
                        "preprocess",
                        site="condorpool",
                        pfn="/usr/bin/pegasus-keg",
                        is_stageable=False,
                        arch=Arch.X86_64,
                        os_type=OS.LINUX
                    )

        findrange = Transformation(
                        "findrange",
                        site="condorpool",
                        pfn="/usr/bin/pegasus-keg",
                        is_stageable=False,
                        arch=Arch.X86_64,
                        os_type=OS.LINUX
                    )

        analyze = Transformation(
                        "analyze",
                        site="condorpool",
                        pfn="/usr/bin/pegasus-keg",
                        is_stageable=False,
                        arch=Arch.X86_64,
                        os_type=OS.LINUX
                    )

        tc = TransformationCatalog().add_transformations(preprocess, findrange, analyze)

        # --- Workflow -----------------------------------------------------------------
        '''
                            [f.b1] - (findrange) - [f.c1] 
                            /                             \\
        [f.a] - (preprocess)                               (analyze) - [f.d]
                            \\                             /
                            [f.b2] - (findrange) - [f.c2]

        '''
        wf = Workflow("blackdiamond")

        fb1 = File("f.b1")
        fb2 = File("f.b2")
        job_preprocess = Job(preprocess)\\
                            .add_args("-a", "preprocess", "-T", "3", "-i", fa, "-o", fb1, fb2)\\
                            .add_inputs(fa)\\
                            .add_outputs(fb1, fb2)

        fc1 = File("f.c1")
        job_findrange_1 = Job(findrange)\\
                            .add_args("-a", "findrange", "-T", "3", "-i", fb1, "-o", fc1)\\
                            .add_inputs(fb1)\\
                            .add_outputs(fc1)

        fc2 = File("f.c2")
        job_findrange_2 = Job(findrange)\\
                            .add_args("-a", "findrange", "-T", "3", "-i", fb2, "-o", fc2)\\
                            .add_inputs(fb2)\\
                            .add_outputs(fc2)

        fd = File("f.d")
        job_analyze = Job(analyze)\\
                        .add_args("-a", "analyze", "-T", "3", "-i", fc1, fc2, "-o", fd)\\
                        .add_inputs(fc1, fc2)\\
                        .add_outputs(fd)

        wf.add_jobs(job_preprocess, job_findrange_1, job_findrange_2, job_analyze)
        wf.add_replica_catalog(rc)
        wf.add_transformation_catalog(tc)

        try:
            wf.plan(submit=True)\\
                .wait()\\
                .analyze()\\
                .statistics()
        except PegasusClientError as e:
            print(e.output)


    """

    _DEFAULT_FILENAME = "workflow.yml"

    def __init__(self, name: str, infer_dependencies: bool = True):
        """
        :param name: name of the :py:class:`~Pegasus.api.workflow.Workflow`
        :type name: str
        :param infer_dependencies: whether or not to automatically compute job dependencies based on input and output files used by each job, defaults to True
        :type infer_dependencies: bool, optional
        :raises ValueError: workflow name may not contain any / or spaces
        """

        if any(c in name for c in "/ "):
            raise ValueError(
                "Invalid workflow name: {}, workflow name may not contain any / or spaces".format(
                    name
                )
            )

        self.name = name
        self.infer_dependencies = infer_dependencies

        # client specific members
        self._submit_dir = None
        self._braindump = None

        self._client = None

        self._path = None

        # sequence unique to this workflow only
        self.sequence = 1

        self.jobs = dict()
        self.dependencies = defaultdict(_JobDependency)

        self.site_catalog = None
        self.transformation_catalog = None
        self.replica_catalog = None

        self.hooks = defaultdict(list)
        self.profiles = defaultdict(dict)
        self.metadata = dict()

    @property
    @_needs_submit_dir
    def braindump(self):
        """Once this workflow has been planned using :py:class:`~Pegasus.api.workflow.Workflow.plan`,
        the braindump file can be accessed for information such as :code:`user`, :code:`submit_dir`, and
        :code:`root_wf_uuid`. For a full list of available attributes, see :py:class:`~Pegasus.braindump.Braindump`.

        .. code-block:: python

            try:
                wf.plan(submit=True)

                print(wf.braindump.user)
                print(wf.braindump.submit_hostname)
                print(wf.braindump.submit_dir)
                print(wf.braindump.root_wf_uuid)
                print(wf.braindump.wf_uuid)
            except PegasusClientError as e:
                print(e.output)


        :getter: returns a :py:class:`~Pegasus.braindump.Braindump` object corresponding to the most recent call of :py:class:`~Pegasus.api.workflow.Workflow.plan`
        :rtype: Pegasus.braindump.Braindump
        :raises PegasusError: :py:class:`~Pegasus.api.workflow.Workflow.plan` must be called before accessing the braindump file
        """
        return self._braindump

    @_chained
    @_needs_client
    def plan(
        self,
        *,
        conf: Optional[str] = None,
        sites: Optional[List[str]] = None,
        output_sites: List[str] = ["local"],
        staging_sites: Optional[Dict[str, str]] = None,
        input_dirs: Optional[List[Union[str, Path]]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        dir: Optional[Union[str, Path]] = None,
        relative_dir: Optional[str] = None,
        random_dir: Union[bool, str, Path] = False,
        cleanup: str = "inplace",
        verbose: int = 0,
        force: bool = False,
        submit: bool = False,
        **kwargs
    ):
        """
        plan(self, conf: Optional[str] = None, sites: Optional[List[str]] = None, output_sites: List[str] = ["local"], staging_sites: Optional[Dict[str, str]] = None, input_dirs: Optional[List[str]] = None, output_dir: Optional[str] = None, dir: Optional[str] = None, relative_dir: Optional[str] = None, random_dir: Union[bool, str, Path] = False, cleanup: str = "inplace", verbose: int = 0, force: bool = False, submit: bool = False, **kwargs)
        Plan the workflow.

        .. code-block:: python

            try:
                wf.plan(verbose=3, submit=True)
            except PegasusClientError as e:
                print(e.output)

        :param conf:  the path to the properties file to use for planning, defaults to None
        :type conf: Optional[str]
        :param sites: list of execution sites on which to map the workflow, defaults to None
        :type sites: Optional[List[str]]
        :param output_sites: the output sites where the data products during workflow execution are transferred to, defaults to :code:`["local"]`
        :type output_sites: List[str]
        :param staging_sites: key, value pairs of execution site to staging site mappings such as :code:`{"condorpool": "staging-site"}`, defaults to None
        :type staging_sites: Optional[Dict[str,str]]
        :param input_dirs: comma separated list of optional input directories where the input files reside on submit host, defaults to None
        :type input_dirs: Optional[List[Union[str, Path]]]
        :param output_dir: an optional output directory where the output files should be transferred to on submit host, defaults to None
        :type output_dir: Optional[Union[str, Path]]
        :param dir: the directory where to generate the executable workflow, defaults to None
        :type dir: Optional[Union[str, Path]]
        :param relative_dir: the relative directory to the base directory where to generate the concrete workflow, defaults to None
        :type relative_dir: Optional[str]
        :param random_dir: if set to :code:`True`, a random timestamp based name will be used for the execution directory that is created by the create dir jobs; else if a path is given as a :code:`str` or :code:`pathlib.Path`, then that will be used as the basename of the directory that is to be created, defaults to False
        :type random_dir: Union[bool, str, Path], optional
        :param cleanup: the cleanup strategy to use. Can be :code:`none|inplace|leaf|constraint`, defaults to :code:`inplace`
        :type cleanup: str, optional
        :param verbose: verbosity, defaults to 0
        :type verbose: int, optional
        :param force: skip reduction of the workflow, resulting in build style dag, defaults to False
        :type force: bool, optional
        :param submit: submit the executable workflow generated, defaults to False
        :type submit: bool, optional
        :raises PegasusClientError: pegasus-plan encountered an error
        :return: self
        """
        # if the workflow has not yet been written to a file and plan is
        # called, write the file to default
        if not self._path:
            # self._path is set by write
            self.write()

        workflow_instance = self._client.plan(
            abstract_workflow=self._path,
            conf=conf,
            sites=sites,
            output_sites=output_sites,
            staging_sites=staging_sites,
            input_dirs=[str(_dir) for _dir in input_dirs] if input_dirs else None,
            output_dir=str(output_dir) if output_dir else None,
            dir=str(dir) if dir else None,
            relative_dir=relative_dir,
            random_dir=random_dir if isinstance(random_dir, bool) else str(random_dir),
            cleanup=cleanup,
            verbose=verbose,
            force=force,
            submit=submit,
            **kwargs,
        )

        self._submit_dir = workflow_instance._submit_dir
        self._braindump = workflow_instance.braindump

    @_chained
    @_needs_client
    def run(self, *, verbose: int = 0, json: bool = False):
        """
        run(self, verbose: int = 0, json: bool = False)
        Run the planned workflow.

        :param verbose: verbosity, defaults to 0
        :type verbose: int, optional
        :param json: Output in JSON format, defaults to False
        :type json: bool
        :raises PegasusClientError: pegasus-run encountered an error
        :return: self
        """
        self._client.run(self._submit_dir, verbose=verbose, json=json)

    @_chained
    @_needs_submit_dir
    @_needs_client
    def status(self, *, long: bool = False, verbose: int = 0):
        """
        status(self, long: bool = False, verbose: int = 0)
        Monitor the workflow by quering Condor and directories.

        :param long: Show all DAG states, including sub-DAGs, default only totals. defaults to False
        :type long: bool, optional
        :param verbose:  verbosity, defaults to False
        :type verbose: int, optional
        :raises PegasusClientError: pegasus-status encountered an error
        :return: self
        """

        self._client.status(self._submit_dir, long=long, verbose=verbose)

    @_chained
    @_needs_submit_dir
    @_needs_client
    def wait(self, *, delay: int = 5):
        """
        wait(self, delay: int = 5)
        Displays progress bar to stdout and blocks until the workflow either
        completes or fails.

        :param delay: refresh rate in seconds of the progress bar, defaults to 5
        :type delay: int, optional
        :raises PegasusClientError: pegasus-status encountered an error
        :return: self
        """

        self._client.wait(self.name, self._submit_dir, delay=delay)

    @_chained
    @_needs_submit_dir
    @_needs_client
    def remove(self, *, verbose: int = 0):
        """
        remove(self, verbose: int = 0)
        Removes this workflow that has been planned and submitted.

        :param verbose:  verbosity, defaults to 0
        :type verbose: int, optional
        :raises PegasusClientError: pegasus-remove encountered an error
        :return: self
        """
        self._client.remove(self._submit_dir, verbose=verbose)

    @_chained
    @_needs_submit_dir
    @_needs_client
    def analyze(self, *, verbose: int = 0):
        """
        analyze(self, verbose: int = 0)
        Debug a workflow.

        :param verbose: verbosity, defaults to 0
        :type verbose: int, optional
        :raises PegasusClientError: pegasus-analyzer encountered an error
        :return: self
        """
        self._client.analyzer(self._submit_dir, verbose=verbose)

    # should wait until wf is done or else we will just get msg:
    # pegasus-monitord still running. Please wait for it to complete.
    @_chained
    @_needs_submit_dir
    @_needs_client
    def statistics(self, *, verbose: int = 0):
        """
        statistics(self, verbose: int = 0)
        Generate statistics about the workflow run.

        :param verbose:  verbosity, defaults to 0
        :type verbose: int, optional
        :raises PegasusClientError: pegasus-statistics encountered an error
        :return: self
        """
        self._client.statistics(self._submit_dir, verbose=verbose)

    @_chained
    @_needs_client
    def graph(
        self,
        no_simplify: bool = True,
        label: Literal[
            "label", "xform", "id", "xform-id", "label-xform", "label-id"
        ] = "label",
        output: Optional[str] = None,
        remove: Optional[List[str]] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        """
        graph(self, no_simplify: bool = True, label: Literal["label", "xform", "id", "xform-id", "label-xform", "label-id"] = "label", output: Optional[str] = None, remove: Optional[List[str]] = None, width: Optional[int] = None, height: Optional[int] = None)
        Convert workflow into a graphviz dot format

        :param no_simplify: when set to :code:`False` a transitive reduction is performed to remove extra edges, defaults to True
        :type no_simplify: bool, optional
        :param label: what attribute to use for labels, defaults to "label"
        :type label: Literal["label", "xform", "id", "xform-id", "label-xform", "label-id"], optional
        :param output: write output to a file; if none is given output is written to stdout, defaults to None
        :type output: Optional[str], optional
        :param remove: remove one or more nodes by transformation name, defaults to None
        :type remove: Optional[List[str]], optional
        :param width: width of the digraph, defaults to None
        :type width: Optional[int], optional
        :param height: height of the digraph, defaults to None
        :type height: Optional[int], optional
        :return: self
        :raises PegasusError: workflow must be written to a file prior to invoking :py:class:`~Pegasus.api.workflow.Workflow.graph` with :py:class:`~Pegasus.api.workflow.Workflow.write` or :py:class:`~Pegasus.api.workflow.Workflow.plan`
        :raises ValueError: label must be one of :code:`label`, :code:`xform`, :code:`id`, :code:`xform-id`, :code:`label-xform`, or :code:`label-id`
        """

        # check that workflow has been written
        if not self._path:
            raise PegasusError(
                "Workflow must be written to a file prior to invoking Workflow.graph"
                "using Workflow.write or Workflow.plan"
            )

        # check that correct label parameter is used
        labels = {"label", "xform", "id", "xform-id", "label-xform", "label-id"}
        if label not in labels:
            raise ValueError(
                "Invalid label: {}, label must be one of {}".format(label, labels)
            )

        self._client.graph(
            self._path, no_simplify, label, output, remove, width, height
        )

    @_chained
    def add_jobs(self, *jobs: Union[Job, SubWorkflow]):
        """
        add_jobs(self, *jobs: Union[Job, SubWorkflow])
        Add one or more jobs at a time to the Workflow

        :raises DuplicateError: a job with the same id already exists in this workflow
        :return: self
        """
        for job in jobs:
            if job._id is None:
                job._id = self._get_next_job_id()

            if job._id in self.jobs:
                raise DuplicateError(
                    "Job with id {} already added to this workflow".format(job._id)
                )

            self.jobs[job._id] = job

    def get_job(self, _id: str):
        """Retrieve the job with the given id

        :param _id: id of the job to be retrieved from the Workflow
        :type _id: str
        :raises NotFoundError: a job with the given id does not exist in this workflow
        :return: the job with the given id
        :rtype: Job
        """
        if _id not in self.jobs:
            raise NotFoundError(
                "job with _id={} not found in this workflow".format(_id)
            )

        return self.jobs[_id]

    def _get_next_job_id(self):
        """Get the next job id from a sequence specific to this workflow

        :return: a new unique job id
        :rtype: str
        """
        next_id = None
        while not next_id or next_id in self.jobs:
            next_id = "ID{:07d}".format(self.sequence)
            self.sequence += 1

        return next_id

    @_chained
    def add_site_catalog(self, sc: SiteCatalog):
        """
        add_site_catalog(self, sc: SiteCatalog)
        Add a :py:class:`~Pegasus.api.site_catalog.SiteCatalog` to this workflow. The contents fo the site catalog
        will be inlined into the same file as this workflow when it is written
        out.

        :param sc: the :py:class:`~Pegasus.api.site_catalog.SiteCatalog` to be added
        :type sc: SiteCatalog
        :raises TypeError: sc must be of type :py:class:`~Pegasus.api.site_catalog.SiteCatalog`
        :raises DuplicateError: a :py:class:`~Pegasus.api.site_catalog.SiteCatalog` has already been added
        :return: self
        """
        if not isinstance(sc, SiteCatalog):
            raise TypeError(
                "invalid catalog: {}; sc must be of type SiteCatalog".format(sc)
            )

        if self.site_catalog is not None:
            raise DuplicateError(
                "a SiteCatalog has already been added to this workflow"
            )

        self.site_catalog = sc

    @_chained
    def add_replica_catalog(self, rc: ReplicaCatalog):
        """
        add_replica_catalog(self, rc: ReplicaCatalog)
        Add a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog` to this workflow.
        The contents fo the replica catalog will be inlined into the same file as
        this workflow when it is written.

        :param rc: the :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog` to be added
        :type rc: ReplicaCatalog
        :raises TypeError: rc must be of type :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog`
        :raises DuplicateError: a :py:class:`~Pegasus.api.replica_catalog.ReplicaCatalog` has already been added
        :return: self
        """
        if not isinstance(rc, ReplicaCatalog):
            raise TypeError(
                "invalid catalog: {}; rc must be of type ReplicaCatalog".format(rc)
            )

        if self.replica_catalog is not None:
            raise DuplicateError(
                "a ReplicaCatalog has already been added to this workflow"
            )

        self.replica_catalog = rc

    @_chained
    def add_transformation_catalog(self, tc: TransformationCatalog):
        """
        add_transformation_catalog(self, tc: TransformationCatalog)
        Add a :py:class:`~Pegasus.api.transformation_catalog.TransformationCatalog`
        to this workflow. The contents fo the transformation catalog will be inlined
        into the same file as this workflow when it is written.

        :param tc: the :py:class:`~Pegasus.api.transformation_catalog.TransformationCatalog` to be added
        :type tc: TransformationCatalog
        :raises TypeError: tc must be of type :py:class:`~Pegasus.api.transformation_catalog.TransformationCatalog`
        :raises DuplicateError: a :py:class:`~Pegasus.api.transformation_catalog.TransformationCatalog` has already been added
        :return: self
        """
        if not isinstance(tc, TransformationCatalog):
            raise TypeError(
                "invalid catalog: {}; rc must be of type TransformationCatalog".format(
                    tc
                )
            )

        if self.transformation_catalog is not None:
            raise DuplicateError(
                "a TransformationCatalog has already been added to this workflow"
            )

        self.transformation_catalog = tc

    @_chained
    def add_dependency(
        self,
        job: Union[Job, SubWorkflow],
        *,
        parents: List[Union[Job, SubWorkflow]] = [],
        children: List[Union[Job, SubWorkflow]] = []
    ):
        """
        add_dependency(self, job: Union[Job, SubWorkflow], *, parents: List[Union[Job, SubWorkflow]] = [], children: List[Union[Job, SubWorkflow]] = [])
        Add parent, child dependencies for a given job.

        .. code-block::python

            # Example 1: set parents of a given job
            wf.add_dependency(job3, parents=[job1, job2])

            # Example 2: set children of a given job
            wf.add_dependency(job1, children=[job2, job3])

            # Example 2 equivalent:
            wf.add_dependency(job1, children=[job2])
            wf.add_dependency(job1, children=[job3])

            # Example 3: set parents and children of a given job
            wf.add_dependency(job3, parents=[job1, job2], children=[job4, job5])


        :param job: the job to which parents and children will be assigned
        :type job: AbstractJob
        :param parents: jobs to be added as parents to this job, defaults to []
        :type parents: list, optional
        :param children: jobs to be added as children of this job, defaults to []
        :type children: list, optional
        :raises ValueError: the given job(s) do not have ids assigned to them
        :raises DuplicateError: a dependency between two jobs already has been added
        :return: self
        """
        # ensure that job, parents, and children are all valid and have ids
        if job._id is None:
            raise ValueError(
                "The given job does not have an id. Either assign one to it upon creation or add the job to this workflow before manually adding its dependencies."
            )

        for parent in parents:
            if parent._id is None:
                raise ValueError(
                    "One of the given parents does not have an id. Either assign one to it upon creation or add the parent job to this workflow before manually adding its dependencies."
                )

        for child in children:
            if child._id is None:
                raise ValueError(
                    "One of the given children does not have an id. Either assign one to it upon creation or add the child job to this workflow before manually adding its dependencies."
                )

        # for each parent, add job as a child
        for parent in parents:
            if parent._id not in self.dependencies:
                self.dependencies[parent._id] = _JobDependency(parent._id, {job._id})
            else:
                if job._id in self.dependencies[parent._id].children_ids:
                    raise DuplicateError(
                        "A dependency already exists between parent id: {} and job id: {}".format(
                            parent._id, job._id
                        )
                    )

                self.dependencies[parent._id].children_ids.add(job._id)

        # for each child, add job as a parent
        if len(children) > 0:
            if job._id not in self.dependencies:
                self.dependencies[job._id] = _JobDependency(job._id, set())

            for child in children:
                if child._id in self.dependencies[job._id].children_ids:
                    raise DuplicateError(
                        "A dependency already exists between job id: {} and child id: {}".format(
                            job._id, child._id
                        )
                    )
                else:
                    self.dependencies[job._id].children_ids.add(child._id)

    def _infer_dependencies(self):
        """Internal function for automatically computing dependencies based on
        Job input and output files. This is called when Workflow.infer_dependencies is
        set to True.
        """

        if self.infer_dependencies:
            mapping = dict()

            """
            create a mapping:
            {
                <filename>: (set(), set())
            }

            where mapping[filename][0] are jobs that use this file as input
            and mapping[filename][1] are jobs that use this file as output
            """
            for _id, job in self.jobs.items():
                if job.stdin:
                    if job.stdin.lfn not in mapping:
                        mapping[job.stdin.lfn] = (set(), set())

                    mapping[job.stdin.lfn][0].add(job)

                if job.stdout:
                    if job.stdout.lfn not in mapping:
                        mapping[job.stdout.lfn] = (set(), set())

                    mapping[job.stdout.lfn][1].add(job)

                if job.stderr:
                    if job.stderr.lfn not in mapping:
                        mapping[job.stderr.lfn] = (set(), set())

                    mapping[job.stderr.lfn][1].add(job)

                """
                for _input in job.inputs:
                    if _input.file.lfn not in mapping:
                        mapping[_input.file.lfn] = (set(), set())

                    mapping[_input.file.lfn][0].add(job)

                for output in job.outputs:
                    if output.file.lfn not in mapping:
                        mapping[output.file.lfn] = (set(), set())

                    mapping[output.file.lfn][1].add(job)
                """
                for io in job.uses:
                    if io.file.lfn not in mapping:
                        mapping[io.file.lfn] = (set(), set())

                    if io._type == _LinkType.INPUT.value:
                        mapping[io.file.lfn][0].add(job)
                    elif io._type == _LinkType.OUTPUT.value:
                        mapping[io.file.lfn][1].add(job)

            """
            Go through the mapping and for each file add dependencies between the
            job producing a file and the jobs consuming the file
            """
            for _, io in mapping.items():
                inputs = io[0]

                if len(io[1]) > 0:
                    # only a single job should produce this file
                    output = io[1].pop()

                    for _input in inputs:
                        try:
                            self.add_dependency(output, children=[_input])
                        except DuplicateError:
                            pass

    @_chained
    def write(self, file: Optional[Union[str, TextIO]] = None, _format: str = "yml"):
        """
        write(self, file: Optional[Union[str, TextIO]] = None, _format: str = "yml")
        Write this workflow to a file. If no file is given,
        it will written to workflow.yml

        :param file: path or file object (opened in "w" mode) to write to, defaults to None
        :type file: Optional[Union[str, TextIO]]
        :param _format: serialized format of the workflow object (this should be left as its default)
        :type _format: str, optional
        :raises PegasusError: :py:class:`~Pegasus.api.site_catalog.SiteCatalog` and :py:class:`~Pegasus.api.transformation_catalog.TransformationCatalog` must be written as a separate file for hierarchical workflows.
        :return: self
        """

        # if subworkflow jobs exist,  tc and sc cannot be inlined
        has_subworkflow_jobs = False
        for _, job in self.jobs.items():
            if isinstance(job, SubWorkflow):
                has_subworkflow_jobs = True
                break

        if has_subworkflow_jobs:
            if self.site_catalog or self.transformation_catalog:
                raise PegasusError(
                    "Site Catalog and Transformation Catalog must be written as a separate file for hierarchical workflows."
                )

        # default file name
        if file is None:
            file = self._DEFAULT_FILENAME

        self._infer_dependencies()
        Writable.write(self, file, _format=_format)

        # save path so that it can be used by Client.plan()
        if isinstance(file, str):
            self._path = file
        elif hasattr(file, "read"):
            self._path = file.name if hasattr(file, "name") else None

    def __json__(self):
        # remove 'pegasus' from tc, rc, sc as it is not needed when they
        # are included in the Workflow which already contains 'pegasus'
        rc = None
        if self.replica_catalog is not None:
            rc = json.loads(json.dumps(self.replica_catalog, cls=_CustomEncoder))
            del rc["pegasus"]

        tc = None
        if self.transformation_catalog is not None:
            tc = json.loads(json.dumps(self.transformation_catalog, cls=_CustomEncoder))
            del tc["pegasus"]

        sc = None
        if self.site_catalog is not None:
            sc = json.loads(json.dumps(self.site_catalog, cls=_CustomEncoder))
            del sc["pegasus"]

        hooks = None
        if len(self.hooks) > 0:
            hooks = {
                hook_name: [hook for hook in values]
                for hook_name, values in self.hooks.items()
            }

        profiles = None
        if len(self.profiles) > 0:
            profiles = dict(self.profiles)

        metadata = None
        if len(self.metadata) > 0:
            metadata = self.metadata

        return _filter_out_nones(
            OrderedDict(
                [
                    ("pegasus", PEGASUS_VERSION),
                    ("name", self.name),
                    ("hooks", hooks),
                    ("profiles", profiles),
                    ("metadata", metadata),
                    ("siteCatalog", sc),
                    ("replicaCatalog", rc),
                    ("transformationCatalog", tc),
                    ("jobs", [job for _id, job in self.jobs.items()]),
                    (
                        "jobDependencies",
                        [dependency for _id, dependency in self.dependencies.items()],
                    ),
                ]
            )
        )
