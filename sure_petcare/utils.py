import os

def mk_enum( name, kv ):
    """
    Emulate enum types found in other languages.

    `name` is the type name to which the enum will be assigned.

    `kv` is either a dict of string -> value mappings or a simple list of
    strings.  In the latter case, numeric values will automatically be assigned.
    """
    if type(kv) is list:
        kv = dict( zip( kv, range(len(kv)) ) )

    class Cls(object):
        __class__ = name
        def __init__( self, d ):
            self._data = d
        def __getattr__( self, name ):
            return self._data[name]
        def find( self, target ):
            return ['%s.%s' % (self.__class__,k,) for k, v in self._data.items() if v == target]

    return Cls( kv )


def getmac():
    """
    Hackish way to obtain an unspecified MAC address.
    """
    mac = None
    folders = os.listdir('/sys/class/net/')
    for interface in folders:
        if interface == 'lo':
            continue
        try:
            mac = open('/sys/class/net/'+interface+'/address').readline()
            # XXX What happens when multiple interfaces are found?  Might
            #     be better to break here to stop at the first MAC which,
            #     on most/many systems, will be the first wired Ethernet
            #     interface.
            # break
        except Exception as e:
            return None
    if mac is not None:
        return mac.strip() #trim new line


def gen_device_id():
    """
    Generates a "unique" client device ID based on MAC address.
    """
    mac_dec = int( getmac().replace( ':', '').replace( '-', '' ), 16 )
    # Use low order bits because upper two octets are low entropy
    return str(mac_dec)[-10:]
