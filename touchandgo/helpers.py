import os
import logging
import signal
import socket

try:
    from daemon import DaemonContext
except ImportError:
    # dude we are on windows
    pass

from datetime import datetime
from lock import Lock
from os import mkdir
from os.path import getmtime, exists, dirname, join
from shutil import copyfile
import sys

from netifaces import interfaces, ifaddresses
from ojota import set_data_source
from qtfaststart.processor import get_index
from qtfaststart.exceptions import FastStartException

from altasetting import Settings
from touchandgo.settings import SKIP_MOOV

import tempfile

LOCKFILE,_ = tempfile.mkstemp(suffix="touchandgo")

log = logging.getLogger('touchandgo.helpers')

def settings_path():
    return os.getenv("HOME", os.getenv('APPDATA'))


def get_settings():
    #settings_file = "%s/.touchandgo/settings.yaml" % settings_path()
    settings_file = os.path.join(settings_path(),".touchandgo","settings.yaml")
    default = join(dirname(__file__), "templates", "settings.yaml")
    print settings_file
    set_config_dir()
    if not exists(settings_file):
        if "win" in sys.platform:
            # well the settings.yaml had a default to /tmp/ on windows that not exist
            import yaml, tempfile
            settings_ = {}
            with open(default) as f:
                settings_ = yaml.load(f)
                settings_["save_path"] = os.path.join(settings_path(), ".touchandgo")
            # create a temporal file and dumps te new save_path
            tmp_stream, temporal_file = tempfile.mkstemp()
            data = yaml.dump(settings_)
            os.write(tmp_stream, data)
            default = temporal_file
        copyfile(default, settings_file)

    settings = Settings(settings_file, default)
    return settings



def get_free_port():
    socket_ = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_.bind(('localhost', 0))
    addr, port = socket_.getsockname()
    socket_.close()
    return port


def is_port_free(port):
    free = True
    socket_ = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        socket_.bind(('localhost', port))
    except socket.error:
        free = False
    socket_.close()

    return free


def get_interface():
    for ifaceName in interfaces():
        addresses = ifaddresses(ifaceName)
        for address in addresses.values():
            for item in address:
                if item.get('netmask') is not None and \
                        not item['addr'].startswith("127") and \
                        not item['addr'].startswith(":") and \
                        len(item['addr']) < 17:
                    return item['addr']


def is_process_running(process_id):
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def daemonize(args, callback):
    with DaemonContext():

        from touchandgo.logger import log_set_up
        log_set_up(True)
        log = logging.getLogger('touchandgo.daemon')
        log.info("running daemon")
        create_process = False
        lock = Lock(LOCKFILE, os.getpid(), args.name, args.sea_ep[0],
                    args.sea_ep[1], args.port)
        if lock.is_locked():
            log.debug("lock active")
            lock_pid = lock.get_pid()
            if not lock.is_same_file(args.name, args.sea_ep[0],
                                     args.sea_ep[1]) \
                    or not is_process_running(lock_pid):
                try:
                    log.debug("killing process %s" % lock_pid)
                    os.kill(lock_pid, signal.SIGQUIT)
                except OSError:
                    pass
                except TypeError:
                    pass
                lock.break_lock()
                create_process = True
        else:
            create_process = True

        if create_process:
            log.debug("creating proccess")
            lock.acquire()
            callback()
            lock.release()
        else:
            log.debug("same daemon process")


def get_lock_diff():
    timediff = 0
    try:
        now = datetime.now()
        timediff = now - datetime.fromtimestamp(getmtime(LOCKFILE + ".lock"))
        timediff = timediff.total_seconds()
    except OSError:
        pass
    return timediff


def set_config_dir():
    data_folder = os.path.join(settings_path(), ".touchandgo")
    if not exists(data_folder):
        mkdir(data_folder)

    set_data_source(data_folder)


def have_moov(video_file):
    if not SKIP_MOOV:
        atoms = {}
        log.info("Checking moov data of %s", video_file)
        try:
            atom_data = get_index(open(video_file, 'rb'))
            for atom in atom_data:
                atoms[atom.name] = atom.position
            log.debug("moov:%(moov)s mdat:%(mdat)s ftyp:%(ftyp)s free:%(free)s",
                    atoms)

            if atoms['moov'] > atoms['mdat']:
                log.info("moov atom after mdat")
                return True, "after_mdat"
            else:
                log.info("moov atom before mdat")
                return True
        except FastStartException as e:
            log.error("Couldn't get Atoms data: %s", str(e))
            return False
    else:
        return True
