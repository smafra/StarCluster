#!/usr/bin/env python
"""
starcluster [<global-opts>] action [<action-opts>] [<action-args> ...]
"""

__description__ = """
StarCluster - (http://web.mit.edu/starcluster)
Please submit bug reports to starcluster@mit.edu
"""

__moredoc__ = """
Each command consists of a class, which has the following properties:

- Must have a class member 'names' which is a list of the names for the command;

- Can optionally have a addopts(self, parser) method which adds options to the
  given parser. This defines command options.
"""

__version__ = "$Revision: 0.9999 $"
__author__ = "Justin Riley <justin.t.riley@gmail.com>"

import os
import sys
import time
from pprint import pprint, pformat
from starcluster import config
from starcluster import static
from starcluster import exception
from starcluster import optcomplete
CmdComplete = optcomplete.CmdComplete
from starcluster.cluster import Cluster
from starcluster.awsutils import get_easy_ec2, get_easy_s3

from starcluster.logger import log

#try:
    #import optcomplete
    #CmdComplete = optcomplete.CmdComplete
#except ImportError,e:
    #optcomplete, CmdComplete = None, object

class CmdBase(CmdComplete):
    parser = None
    opts = None
    gopts = None

    @property
    def goptions_dict(self):
        return dict(self.gopts.__dict__)

    @property
    def options_dict(self):
        return dict(self.opts.__dict__)

    @property
    def specified_options_dict(self):
        """ only return options with non-None value """
        specified = {}
        options = self.options_dict
        for opt in options:
            if options[opt]:
                specified[opt] = options[opt]
        return specified

class CmdStart(CmdBase):
    """Start a StarCluster cluster """
    names = ['start']

    @property
    def completer(self):
        if optcomplete:
            try:
                cfg = config.StarClusterConfig()
                cfg.load()
                return optcomplete.ListCompleter(cfg.get_cluster_names())
            except Exception, e:
                log.error('something went wrong fix me: %s' % e)

    def addopts(self, parser):
        opt = parser.add_option("-x","--no-create", dest="NO_CREATE",
            action="store_true", default=False, help="Do not launch new ec2 \
instances when starting cluster (uses existing instances instead)")
        parser.add_option("-l","--login-master", dest="LOGIN_MASTER",
            action="store_true", default=False, 
            help="ssh to ec2 cluster master node after launch")
        parser.add_option("-t","--tag", dest="CLUSTER_TAG",
            action="store", type="string", default=time.strftime("%Y%m%d%H%M"), 
            help="tag to identify cluster")
        parser.add_option("-d","--description", dest="CLUSTER_DESCRIPTION",
            action="store", type="string", 
            default="Cluster requested at %s" % time.strftime("%Y%m%d%H%M"), 
            help="brief description of cluster")
        parser.add_option("-s","--cluster-size", dest="CLUSTER_SIZE",
            action="store", type="int", default=None, 
            help="number of ec2 nodes to launch")
        parser.add_option("-u","--cluster-user", dest="CLUSTER_USER",
            action="store", type="string", default=None, 
            help="name of user to create on cluster (defaults to sgeadmin)")
        opt = parser.add_option("-S","--cluster-shell", dest="CLUSTER_SHELL",
            action="store", choices=static.AVAILABLE_SHELLS.keys(),
            default=None, help="shell for cluster user ")
        if optcomplete:
            opt.completer = optcomplete.ListCompleter(opt.choices)
        parser.add_option("-m","--master-image-id", dest="MASTER_IMAGE_ID",
            action="store", type="string", default=None, 
            help="image to use for master")
        parser.add_option("-n","--node-image-id", dest="NODE_IMAGE_ID",
            action="store", type="string", default=None, 
            help="image to use for node")
        opt = parser.add_option("-i","--instance-type", dest="INSTANCE_TYPE",
            action="store", choices=static.INSTANCE_TYPES.keys(),
            default=None, help="specify machine type for cluster")
        if optcomplete:
            opt.completer = optcomplete.ListCompleter(opt.choices)
        parser.add_option("-a","--availability-zone", dest="AVAILABILITY_ZONE",
            action="store", type="string", default=None, 
            help="availability zone to launch ec2 instances in ")
        parser.add_option("-k","--keyname", dest="KEYNAME",
            action="store", type="string", default=None, 
            help="name of AWS ssh key to use for cluster")
        parser.add_option("-K","--key-location", dest="KEY_LOCATION",
            action="store", type="string", default=None, metavar="FILE",
            help="path to ssh key used for this cluster")
        parser.add_option("-v","--volume", dest="VOLUME",
            action="store", type="string", default=None, 
            help="EBS volume to attach to master node")
        parser.add_option("-D","--volume-device", dest="VOLUME_DEVICE",
            action="store", type="string", default=None, 
            help="Device label to use for EBS volume")
        parser.add_option("-p","--volume-partition", dest="VOLUME_PARTITION",
            action="store", type="string", default=None, 
            help="EBS Volume partition to mount on master node")

    def execute(self, args):
        if not args:
            self.parser.error("please specify a cluster")
        config_file = self.goptions_dict.get("CONFIG")
        cfg = config.StarClusterConfig(config_file); cfg.load()
        for cluster_name in args:
            try:
                cluster = cfg.get_cluster(cluster_name)
                cluster.update(self.specified_options_dict)
                #pprint(cluster)
            except exception.ClusterDoesNotExist,e:
                log.warn(e.explain())
                aws_environ = cfg.get_aws_credentials()
                cluster_options = self.specified_options_dict
                kwargs = {}
                kwargs.update(aws_environ)
                kwargs.update(cluster_options)
                cluster = Cluster(**kwargs)
            if cluster.is_valid():
                cluster.start(create=not self.opts.NO_CREATE)
            else:
                print 'not valid cluster'

class CmdStop(CmdBase):
    """Shutdown a StarCluster cluster"""
    names = ['stop']
    def execute(self, args):
        if not args:
            self.parser.error("please specify a cluster")
        config_file = self.goptions_dict.get("CONFIG")
        cfg = config.StarClusterConfig(config_file); cfg.load()
        ec2 = get_easy_ec2()
        for cluster_name in args:
            if not cluster_name.startswith(static.SECURITY_GROUP_PREFIX):
                cluster_name = static.SECURITY_GROUP_TEMPLATE % cluster_name
            try:
                cluster = ec2.get_security_group(cluster_name)
                for node in cluster.instances():
                    log.info('Shutting down %s' % node.id)
                    node.stop()
                log.info('Removing cluster security group %s' % cluster.name)
                cluster.delete()
            except Exception,e:
                #print e
                log.error("cluster %s does not exist" % cluster_name)

class CmdSshMaster(CmdBase):
    """SSH to StarCluster master node"""
    names = ['sshmaster']
    def execute(self, args):
        log.error('unimplemented')
        #pprint(args)
        #pprint(self.gopts)
        #pprint(self.opts)

class CmdSshNode(CmdBase):
    """SSH to StarCluster node"""
    names = ['sshnode']
    def execute(self, args):
        log.error('unimplemented')
        #pprint(args)
        #pprint(self.gopts)
        #pprint(self.opts)

class CmdListClusters(CmdBase):
    """List all StarCluster clusters"""
    names = ['listclusters']
    def execute(self, args):
        ec2 = get_easy_ec2()
        sgs = ec2.get_security_groups()
        starcluster_groups = []
        for sg in sgs:
            is_starcluster = sg.name.startswith(static.SECURITY_GROUP_PREFIX)
            if is_starcluster and sg.name != static.MASTER_GROUP:
                starcluster_groups.append(sg)
        if starcluster_groups:
            for scg in starcluster_groups:
                print scg.name
                for node in scg.instances():
                    print "  %s" % node.dns_name
        else:
            log.info("No clusters found...")

class CmdCreateAmi(CmdBase):
    """Create a new image (AMI) from a currently running EC2 instance"""
    names = ['createami']
    def execute(self, args):
        log.error('unimplemented')
        #pprint(args)
        #pprint(self.gopts)
        #pprint(self.opts)

class CmdCreateVolume(CmdBase):
    """Create a new EBS volume for use with StarCluster"""
    names = ['createvolume']
    def execute(self, args):
        log.error('unimplemented')
        #pprint(args)
        #pprint(self.gopts)
        #pprint(self.opts)

class CmdListImages(CmdBase):
    """List all registered EC2 images (AMIs)"""
    names = ['listimages']
    def execute(self, args):
        def get_key(obj):
            return obj.location
        ec2 = get_easy_ec2()
        counter = 0
        images = ec2.registered_images
        images.sort(key=get_key)
        for image in images:
            name = image.location.split('/')[1].split('.manifest.xml')[0]
            print "[%d] %s (%s)" % (counter, image.id, name)
            counter += 1

class CmdListBuckets(CmdBase):
    """List all S3 buckets"""
    names = ['listbuckets']
    def execute(self, args):
        s3 = get_easy_s3()
        buckets = s3.list_buckets()

class CmdShowImage(CmdBase):
    """Show all files on S3 for an EC2 image (AMI)"""
    names = ['showimage']
    def execute(self, args):
        if not args:
            self.parser.error('please specify an AMI id')
        for arg in args:
            ec2 = get_easy_ec2()
            files = ec2.get_image_files(arg)
            for file in files:
                print file.name
   
class CmdShowBucket(CmdBase):
    """Show all files in a S3 bucket"""
    names = ['showbucket']
    def execute(self, args):
        if not args:
            self.parser.error('please specify a S3 bucket')
        for arg in args:
            s3 = get_easy_s3()
            bucket = s3.get_bucket(arg)
            for file in bucket.list():
                print file.name

class CmdRemoveImage(CmdBase):
    """Deregister an EC2 image (AMI) and remove it from S3"""
    names = ['removeimage']
    def execute(self, args):
        log.error('unimplemented')
        #pprint(args)
        #pprint(self.gopts)
        #pprint(self.opts)

class CmdHelp:
    """Show StarCluster usage"""
    names =['help']
    def execute(self, args):
        import optparse
        if args:
            cmdname = args[0]
            try:
                sc = subcmds_map[cmdname]
                lparser = optparse.OptionParser(sc.__doc__.strip())
                if hasattr(sc, 'addopts'):
                    sc.addopts(lparser)
                lparser.print_help()
            except KeyError:
                raise SystemExit("Error: invalid command '%s'" % cmdname)
        else:
            gparser.parse_args(['--help'])

def get_description():
    return __description__.replace('\n','',1)

def parse_subcommands(gparser, subcmds):

    """Parse given global arguments, find subcommand from given list of
    subcommand objects, parse local arguments and return a tuple of global
    options, selected command object, command options, and command arguments.
    Call execute() on the command object to run. The command object has members
    'gopts' and 'opts' set for global and command options respectively, you
    don't need to call execute with those but you could if you wanted to."""

    import optparse
    global subcmds_map # needed for help command only.

    print get_description()

    # Build map of name -> command and docstring.
    subcmds_map = {}
    gparser.usage += '\n\nAvailable Actions\n'
    for sc in subcmds:
        gparser.usage += '- %s: %s\n' % (', '.join(sc.names),
                                       sc.__doc__.splitlines()[0])
        for n in sc.names:
            assert n not in subcmds_map
            subcmds_map[n] = sc

    # Declare and parse global options.
    gparser.disable_interspersed_args()

    gopts, args = gparser.parse_args()
    if not args:
        gparser.print_help()
        raise SystemExit("\nError: you must specify an action.")
    subcmdname, subargs = args[0], args[1:]

    # Parse command arguments and invoke command.
    try:
        sc = subcmds_map[subcmdname]
        lparser = optparse.OptionParser(sc.__doc__.strip())
        if hasattr(sc, 'addopts'):
            sc.addopts(lparser)
        sc.parser = lparser
        sc.gopts = gopts
        sc.opts, subsubargs = lparser.parse_args(subargs)
    except KeyError:
        raise SystemExit("Error: invalid command '%s'" % subcmdname)

    return gopts, sc, sc.opts, subsubargs

def main():
    # Create global options parser.
    global gparser # only need for 'help' command (optional)
    import optparse
    gparser = optparse.OptionParser(__doc__.strip(), version=__version__)
    gparser.add_option("-d","--debug", dest="DEBUG", action="store_true",
        default=False,
        help="print debug messages (useful for diagnosing problems)")
    gparser.add_option("-c","--config", dest="CONFIG", action="store",
        metavar="FILE",
        help="use alternate config file (default: ~/.starclustercfg)")

    # Declare subcommands.
    subcmds = [
        CmdStart(),
        CmdListClusters(),
        CmdCreateAmi(),
        CmdCreateVolume(),
        CmdStop(),
        CmdSshMaster(),
        CmdSshNode(),
        CmdListBuckets(),
        CmdShowBucket(),
        CmdListImages(),
        CmdRemoveImage(),
        CmdShowImage(),
        CmdHelp(),
    ]

    # subcommand completions
    scmap = {}
    for sc in subcmds:
        for n in sc.names:
            scmap[n] = sc
  
    if optcomplete:
        listcter = optcomplete.ListCompleter(scmap.keys())
        subcter = optcomplete.NoneCompleter()
        optcomplete.autocomplete(
            gparser, listcter, None, subcter, subcommands=scmap)
    elif 'COMP_LINE' in os.environ:
        return -1

    gopts, sc, opts, args = parse_subcommands(gparser, subcmds)
    sc.execute(args)

def test():
    pass

if os.environ.has_key('starcluster_commands_test'):
    test()
elif __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print "Interrupted, exiting."
