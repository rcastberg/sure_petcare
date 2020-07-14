#!/usr/bin/python3
"""
Access the sure petcare access information
"""

import json
import os
import pickle
import requests
from datetime import datetime, timezone
import sure_petcare.utils as utils
from .utils import mk_enum

CACHE_FILE = os.path.expanduser( '~/.surepet.cache' )
# version of cache structure
CACHE_VERSION = 2

DIRECTION ={0:'Looked through',1:'Entered House',2:'Left House'}
INOUT_STATUS = {1 : 'Inside', 2 : 'Outside'}
# Added by A. Greulich:
PROFILES = {2 : 'Free to leave (outdoor pet)', 3 : 'Locked in (indoor pet)'}

# The following event types are known, eg EVT.CURFEW.
EVT = mk_enum( 'EVT',
               {'MOVE': 0,
                'MOVE_UID': 7, # movement of unknown animal
                'BAT_WARN': 1,
                'LOCK_ST': 6,
                'USR_IFO': 12,
                'USR_NEW': 17,
                'CURFEW': 20,
                } )

LK_MOD = mk_enum( 'LK_MOD',
                  {'UNLOCKED': 0,
                   'LOCKED_IN': 1,
                   'LOCKED_OUT': 2,
                   'LOCKED_ALL': 3,
                   'CURFEW': 4,
                   'CURFEW_LOCKED': -1,
                   'CURFEW_UNLOCKED': -2,
                   'CURFEW_UNKNOWN': -3,
                   } )

PROD_ID = mk_enum( 'PROD_ID',
                   {'ROUTER': 1,
                    'PET_FLAP': 3,   # Pet Door Connect
                    'CAT_FLAP': 6,   # Cat Door Connect
                    } )

LOC = mk_enum( 'LOC',
               {'INSIDE': 1,
                'OUTSIDE': 2,
                'UNKNOWN': -1,
                } )

# Added by A. Greulich
TAG = mk_enum( 'LOC',
               {'INDOOR': 3,
                'OUTDOOR': 2,
                'UNKNOWN': -1,
                } )


# REST API endpoints (no trailing slash)
_URL_AUTH = 'https://app.api.surehub.io/api/auth/login'
_URL_HOUSEHOLD = 'https://app.api.surehub.io/api/household'
_URL_DEV = 'https://app.api.surehub.io/api/device'
_URL_TIMELINE = 'https://app.api.surehub.io/api/timeline'
_URL_PET = 'https://app.api.surehub.io/api/pet'
API_USER_AGENT = 'Mozilla/5.0 (Linux; Android 7.0; SM-G930F Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/64.0.3282.137 Mobile Safari/537.36'

_HARD_RATE_LIMIT = 60


class SurePetFlapAPI(object):
    """Class to take care of network communication with SurePet's products.

    Unless you want to parse data from Sure directly, instantiate SurePetFlap()
    rather than this class directly.  The constructor arguments are the same as
    below.
    """

    def __init__( self, email_address = None, password = None, household_id = None, device_id = None, cache_file = CACHE_FILE, debug = False ):
        """
        `email_address` and `password` are self explanatory.  They are cached on
        disc file `cache_file` and are therefore only mandatory on first
        invocation (or if either have been changed).

        `household_id` need only be specified if your account has access to more
        than one household and you know its ID.  You can find out which is which
        by examining property `households`.

        You can set the default household after the fact by assigning the
        appropriate ID to property `default_household` if the initial default
        is not to your liking.  This assignment will persist in the cache, so
        you only need do it the once.  Do not set it to None or you will get
        exceptions.

        `device_id` is the ID of *this* client.  If none supplied, a plausible,
        unique-ish default is supplied.

        Cache
        -----

        This API makes aggressive use of caching.  This is not optional
        because use of this API must never be responsible for more impact on
        Sure's servers than the official app.

        In order to ensure that the cache is written back to disc, instances of
        this class must be used as a context manager.  Any API call that could
        change cache state *can only* be called from within a context block.

        The cache is written out at the end of the context block.  You can
        continue to query the API outside of the context block, but any attempt
        to update or modify anything will result in exception SPAPIReadOnly.

        Example:
        ```
        with SurePetFlap() as api:
            api.update_pet_status()
        for pet_id, info in api.pets.items():
            print( '%s is %s' % (info['name'], api.get_pet_location(pet_id),) )
        ```

        Note that the disc copy of the cache is locked while in context, so
        update what you need and leave context as soon as possible.
        """
        # cache_status is None to indicate that it hasn't been initialised
        self.cache_file = cache_file or CACHE_FILE
        self.cache_lockfile = self.cache_file + '.lock'
        self._init_default_household = household_id
        self._init_email = email_address
        self._init_pw = password
        self._load_cache()
        self.__read_only = True
        if (email_address is None or password is None) and self.cache['AuthToken'] is None:
            raise ValueError('No cached credentials and none provided')
        self.debug = debug
        self.s = requests.session()
        if debug:
            self.req_count = self.req_rx_bytes = 0
            self.s.hooks['response'].append( self._log_req )
        if device_id is None:
            self.device_id = utils.gen_device_id()
        else:
            self.device_id = device_id

    #
    # Query methods (with helper properties that use defaults where possible)
    #

    @property
    def update_required( self ):
        """Indicates whether an `update()` call is **required** for correct
           function, not whether the cache is up-to-date."""
        return (self.cache['AuthToken'] is None or
                self.households is None or
                self.household.get('pets') is None)

    @property
    def battery( self ):
        "Battery level of default flap at default household"
        return self.get_battery()
    def get_battery( self, household_id = None, flap_id = None ):
        """
        Return battery voltage (assuming four batteries).  The level at which
        you should replace them depends on the chemistry (type) of the battery.
        As a guide, alkalines should be replaced before they reach 1.2V.  Use
        the official app to get better advice.
        """
        household_id = household_id or self.default_household
        flap_id = flap_id or self.get_default_flap( household_id )
        try:
            return self.all_flap_status[household_id][flap_id]['battery'] / 4.0
        except KeyError:
            raise SPAPIUnitialised()

    @property
    def pets( self ):
        return self.get_pets()
    def get_pets( self, household_id = None ):
        "Return dict of pets.  Default household used if not specified."
        household_id = household_id or self.default_household
        try:
            return self.households[household_id]['pets']
        except KeyError:
            raise SPAPIUnitialised()

    def get_pet_id_by_name( self, name, household_id = None ):
        """
        Returns the numeric ID (not the tag ID) of the pet by name.  Match is
        case insensitive and the first pet found with that name is returned.
        Default household used if not specified.
        """
        household_id = household_id or self.default_household
        for pet_id, petdata in self.get_pets( household_id ).items():
            if petdata['name'].lower() == name.lower():
                return pet_id

    def get_pet_location( self, pet_id, household_id = None ):
        """
        Returns one of enum LOC indicating last known movement of the pet.
        Default household used if not specified.
        """
        household_id = household_id or self.default_household
        if pet_id not in self.all_pet_status[household_id]:
            raise SPAPIUnknownPet()
        return self.all_pet_status[household_id][pet_id]['where']

    # Added by A. Greulich
    def get_pet_profile( self, pet_id, household_id = None ):
        """
        Returns one of enum TAG indicating if cat is locked in or not.
        Default household used if not specified.
        """
        household_id = household_id or self.default_household
        if pet_id not in self.all_pet_status[household_id]:
            raise SPAPIUnknownPet()
        return self.all_pet_status[household_id][pet_id]['profile']

    def get_lock_mode( self, flap_id = None, household_id = None ):
        """
        Returns one of enum LK_MOD indicating flap lock mode.  Default household
        and flap used if not specified.
        """
        household_id = household_id or self.default_household
        household = self.households[household_id]
        if flap_id is None:
            flap_id = household['default_flap']
        lock_data = self.all_flap_status[household_id][flap_id]['locking']
        if lock_data['mode'] == LK_MOD.CURFEW:
            if lock_data['curfew']['locked']:
                return LK_MOD.CURFEW_LOCKED
            else:
                return LK_MOD.CURFEW_UNLOCKED
        return lock_data['mode']

    #
    # Default household and device helpers
    #

    @property
    def default_household( self ):
        "Get the default house ID."
        return self.cache['default_household']
    @default_household.setter
    def default_household( self, id ):
        "Set the default household ID."
        if self.__read_only:
            raise SPAPIReadOnly()
        self.cache['default_household'] = id
    @property
    def household( self ):
        "Return default household dict"
        return self.households[self.default_household]

    @property
    def default_router( self ):
        "Returns the default router ID for the default household"
        return self.get_default_router()
    def get_default_router( self, household_id = None ):
        "Get the default router ID."
        household_id = household_id or self.default_household
        return self.households[household_id]['default_router']
    def set_default_router( self, household_id, rid ):
        "Set the default router ID."
        if self.__read_only:
            raise SPAPIReadOnly()
        self.households[household_id]['default_router'] = rid

    @property
    def default_flap( self ):
        "Returns the default flap ID for the default household"
        return self.get_default_flap()
    def get_default_flap( self, household_id = None ):
        "Get the default flap ID."
        household_id = household_id or self.default_household
        return self.households[household_id]['default_flap']
    def set_default_flap( self, household_id, flap_id ):
        "Set the default flap ID."
        if self.__read_only:
            raise SPAPIReadOnly()
        self.households[household_id]['default_flap'] = flap_id

    #
    # These properties return respective data for all households as a dict
    # indexed by household ID (most of them indexed by another ID).
    #

    @property
    def households( self ):
        """
        Return dict of households which include name, timezone information
        suitable for use with pytz and also pet info.

        NB: Indexed by household ID.
        """
        return self.cache['households']
    @households.setter
    def households( self, data ):
        "Set household data."
        if self.__read_only:
            raise SPAPIReadOnly()
        self.cache['households'] = data

    @property
    def router_status( self ):
        "Dict of all routers in default household"
        return self.all_router_status[self.default_household]
    @property
    def all_router_status( self, household_id = None ):
        "Dict of all routers indexed by household and router IDs"
        return self.cache['router_status']
    @property
    def flap_status( self ):
        "Dict of all flaps for default household"
        return self.all_flap_status[self.default_household]
    @property
    def all_flap_status( self ):
        "Dict of all flaps indexed by household and router IDs"
        return self.cache['flap_status']
    @property
    def pet_status( self ):
        "Dict of all pets for default household"
        return self.all_pet_status[self.default_household]
    @property
    def all_pet_status( self ):
        "Dict of all pets indexed by household and pet IDs"
        return self.cache['pet_status']
    @property
    def pet_timeline( self ):
        "Pet events for default household (subset of house timeline)"
        return self.all_pet_timeline[self.default_household]
    @property
    def all_pet_timeline( self ):
        "Dict of pet events indexed by household ID (subset of house timeline)"
        return self.cache['pet_timeline']
    @property
    def house_timeline( self ):
        "Events for default household"
        return self.all_house_timeline[self.default_household]
    @property
    def all_house_timeline( self ):
        "Dict of household events indexed by household ID"
        return self.cache['house_timeline']

    #
    # Update methods.  USE SPARINGLY!
    #

    def update( self ):
        """
        Update everything.  Must be invoked once, but please, only once.  Call
        the individual update methods according to your applications needs.
        """
        self.update_authtoken()
        self.update_households()
        self.update_device_ids()
        self.update_pet_info()
        self.update_pet_status()
        self.update_flap_status()
        #self.update_router_status()
        # XXX For now, router status contains little of interest and isn't worth
        #     the API call.  Call it explicitly if you need this (which you
        #     should be doing anyway to save on bandwidth).
        self.update_timelines()

    def update_authtoken( self, force = False ):
        """
        Update cache with authentication token if missing.  Use `force = True`
        when the token expires (the API generally does this automatically).
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        if self.cache['AuthToken'] is not None and not force:
            return
        # Allow constructor to override email/pw should they change
        data = {"email_address": self._init_email or self.cache['email'],
                "password": self._init_pw or self.cache['pw'],
                "device_id": self.device_id,
                }
        headers=self._create_header()
        response = self.s.post(_URL_AUTH, headers=headers, json=data)
        if response.status_code == 401:
            raise SPAPIAuthError()
        response_data = response.json()
        self.cache['AuthToken'] = response_data['data']['token']

    def update_households( self, force = False ):
        """
        Update cache with info about the household(s) associated with the account.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        if self.households is not None and not force:
            return
        params = ( # XXX Could we merge update_households() with update_pet_info()?
            ('with[]', ['household', 'timezone',],), #'pet',
        )
        headers=self._create_header()
        response_household = self._api_get(_URL_HOUSEHOLD, headers=headers, params=params)
        response_household = response_household.json()
        self.households = {
            x['id']: {'name': x['name'],
                      'olson_tz': x['timezone']['timezone'],
                      'utc_offset':  x['timezone']['utc_offset'],
                      'default_router': None,
                      'default_flap': None,
                      } for x in response_household['data']
            }
        # default_household may have been set by the constructor, but override
        # it anyway if the specified ID wasn't in the data just fetched.
        if self.default_household not in self.households:
            self.default_household = response_household['data'][0]['id']

    def update_device_ids( self, household_id = None, force = False ):
        """
        Update cache with list of router and flap IDs for each household.  The
        default router and flap are set to the first ones found.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        household = self.households[household_id]
        if (household['default_router'] is not None and
            household['default_flap'] is not None and not force):
            return
        params = (
            ('with[]', 'children'),
        )
        routers = household['routers'] = {}
        flaps = household['flaps'] = {}
        url = '%s/%s/device' % (_URL_HOUSEHOLD, household_id,)
        response_children = self._get_data(url, params)
        for device in response_children['data']:
            if device['product_id'] in (PROD_ID.PET_FLAP, PROD_ID.CAT_FLAP): # Catflap
                flaps[device['id']] = device['name']
            elif device['product_id'] == PROD_ID.ROUTER: # Router
                routers[device['id']] = device['name']
        household['default_flap'] = list(flaps.keys())[0]
        household['default_router'] = list(routers.keys())[0]

    def update_pet_info( self, household_id = None, force = False ):
        """
        Update cache with pet information.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        household = self.households[household_id]
        if household.get('pets') is not None and not force:
            return
        params = (
            ('with[]', ['photo', 'tag']),
        )
        url = '%s/%s/pet' % (_URL_HOUSEHOLD, household_id,)
        response_pets = self._get_data(url, params)
        household['pets'] = {
            x['id']: {'name': x['name'],
                      'tag_id': x['tag_id'],
                      'photo': x.get('photo', {}).get('location')
                      } for x in response_pets['data']
            }

    def update_flap_status( self, household_id = None ):
        """
        Update flap status.  Default household used if not specified.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        household = self.households[household_id]
        for flap_id in household['flaps']:
            url = '%s/%s/status' % (_URL_DEV, flap_id,)
            response = self._get_data(url)
            self.cache['flap_status'].setdefault( household_id, {} )[flap_id] = response['data']

    def update_router_status( self, household_id = None ):
        """
        Update router status.  Don't call unless you really need to because
        there's not much of interest here.  Default household used if not
        specified.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        household = self.households[household_id]
        for rid in household['routers']:
            url = '%s/%s/status' % (_URL_DEV, rid,)
            response = self._get_data(url)
            self.cache['router_status'].setdefault( household_id, {} )[rid] = response['data']

    def update_timelines( self, household_id = None ):
        """
        Update household event timeline and curfew lock status.  Default
        household used if not specified.

        NB: This call reconstructs the data that would be returned by the
            timeline/pet REST call rather than making N such calls for N pets
            in order to minimise load on servers which means that pet timelines
            contain fewer entries than they would if you have multiple pets
            (because each REST endpoint nominally returns 50 records).

            This might only be a problem if you have multiple pets and the most
            active pet is substantially more so than the least active.  This
            may be addressed in a future version of these bindings if it seems
            to be a problem.  However, unless your animals are exceptionally
            active, a call once a day should be enough to capture complete
            history.

            Another side-effect is that the pet timeline has non-movement
            related events (eg curfew lock/unlock events) filtered.  It
            necessarily also must filter out unidentified movements because
            it's impossible to which pet to attribute such events.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        url = '%s/household/%s' % (_URL_TIMELINE, household_id,)
        response = self._get_data(url, params)
        self.cache['house_timeline'][household_id] = response['data']

        # Build per-pet timeline
        tag_lut = {v['tag_id']: k for k, v in self.get_pets( household_id ).items()}
        self.cache['pet_timeline'][household_id] = {
            pet_id: [x for x in self.cache['house_timeline'][household_id]
                       if x['type'] == EVT.MOVE and tag_lut[x['movements'][0]['tag_id']] == pet_id]
                for pet_id in self.get_pets( household_id ).keys()
           }


    def update_pet_status( self, household_id = None ):
        """
        Update pet status.  Default household used if not specified.
        """
        if self.__read_only:
            raise SPAPIReadOnly()
        household_id = household_id or self.default_household
        self.cache['pet_status'][household_id] = {}

        # Added by A. Greulich, read profiles in a 'tags' hash:
        params = (
            ('with[]', 'tags'),
        )
        headers = self._create_header()
        response = self._get_data(_URL_DEV, params)
        tags = [x for x in response["data"] if "tags" in x][0]["tags"]

        # traverse pets
        for pet_id in self.get_pets( household_id ):
            url = '%s/%s/position' % (_URL_PET, pet_id,)
            headers = self._create_header()
            response = self._get_data(url)
            # Line added by A. Greulich:
            response['data']['profile'] = [x['profile'] for x in tags if x['id'] == response['data']['tag_id']][0]
            self.cache['pet_status'][household_id][pet_id] = response['data']



    #
    # Low level remote API wrappers.  Do not use.
    #

    def _get_data( self, url, params = None ):
        if self.__read_only:
            raise SPAPIReadOnly()
        headers = None
        if url in self.cache:
            time_since_last = datetime.now(timezone.utc) - self.cache[url]['ts']
            # Return cached data unless older than hard rate limit
            if time_since_last.total_seconds() > _HARD_RATE_LIMIT:
                headers = self._create_header(ETag=self.cache[url]['ETag'])
        else:
            headers = self._create_header()
        if headers is not None:
            response = self._api_get(url, headers=headers, params=params)
            if response.status_code in [304, 404, 500, 502, 503, 504,]:
                # Used cached data in event of (respectively), not modified,
                # server error, server overload, server unavailable and gateway
                # timeout.  Doesn't cope with such events absent cached data,
                # but hopefully that is sufficiently rare not to bother with.
                if response.status_code == 404:
                    raise IndexError( url )
                if response.status_code == 304:
                    # Can only get here if there is a cached response
                    self.cache[url]['ts'] = datetime.now(timezone.utc)
                return self.cache[url]['LastData']
            self.cache[url] = {
                'LastData': response.json(),
                'ETag': response.headers['ETag'].strip( '"' ),
                'ts': datetime.now(timezone.utc),
                }
        return self.cache[url]['LastData']

    def _create_header( self, ETag = None ):
        headers={
            'Connection': 'keep-alive',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://surepetcare.io',
            'User-Agent': API_USER_AGENT,
            'Referer': 'https://surepetcare.io/',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en-GB;q=0.9',
            'X-Requested-With': 'com.sureflap.surepetcare',
        }

        if self.cache['AuthToken'] is not None:
            headers['Authorization']='Bearer ' + self.cache['AuthToken']
        if ETag is not None:
            headers['If-None-Match'] = ETag
        return headers

    def _api_get( self, url, *args, **kwargs ):
        r = self.s.get( url, *args, **kwargs )
        if r.status_code == 401:
            # Retry once
            self.update_authtoken( force = True )
            if 'headers' in kwargs and 'Authorization' in kwargs['headers']:
                kwargs['headers']['Authorization']='Bearer ' + self.cache['AuthToken']
                r = self.s.get( url, *args, **kwargs )
            else:
                raise SPAPIException( 'Auth required but not present in header' )
        return r

    def _log_req( self, r, *args, **kwargs ):
        """
        Debugging aid: print network requests
        """
        l = len( '\n'.join( ': '.join(x) for x in r.headers.items() ) )
        l += len(r.content)
        self.req_count += 1
        self.req_rx_bytes += l
        print( 'requests: %s %s -> %s (%0.3f kiB, total %0.3f kiB in %s requests)' % (r.request.method, r.request.url, r.status_code, l/1024.0, self.req_rx_bytes/1024.0, self.req_count,) )

    #
    # Cache management
    #

    def _load_cache( self ):
        """
        Read cache file.  The cache is written by the context `__exit__()`
        method.
        """
        # Cache locking is done by the context manager methods.

        default_cache = {
            'AuthToken': None,
            'households': None,
            'default_household': self._init_default_household,
            'router_status': {},  # indexed by household
            'flap_status': {},  # indexed by household
            'pet_status': {},  # indexed by household
            'pet_timeline': {},  # indexed by household
            'house_timeline': {},  # indexed by household
            'version': CACHE_VERSION  # of cache structure.
        }

        try:
            with open( self.cache_file, 'rb' ) as f:
                self.cache = pickle.load( f )
        except (pickle.PickleError, OSError,):
            self.cache = default_cache

        if self.cache['version'] != CACHE_VERSION:
            # reset cache, but try to preserve auth credentials
            auth_token = self.cache.get('AuthToken')
            self.cache = default_cache
            self.cache['AuthToken'] = auth_token

    def __enter__( self ):
        """
        Entering context unlocks the cache for modification and update.
        """
        if os.path.exists( self.cache_lockfile ):
            raise SPAPICacheLocked()
        else:
            # Yeah, there are better ways of doing this, but I don't want to
            # add to the API's dependencies for the sake of compatibility.
            with open( self.cache_lockfile, 'w' ) as lf:
                # Conveniently, this also tests that the cache file location
                # is writeable.
                lf.write( str(os.getpid()) )
            # Check to make sure that we didn't get gazumped
            with open( self.cache_lockfile, 'r' ) as lf:
                if int(lf.read()) != os.getpid():
                    raise SPAPICacheLocked()
            # We've got a solid lock.  Hopefully.
        self._load_cache()
        self.__read_only = False
        return self

    def __exit__( self, exc_type, exc_value, traceback ):
        """
        Exiting context locks the cache to prevent further modification and
        also flushes the cache to disc.
        """
        self.__read_only = True
        with open( self.cache_file, 'wb' ) as f:
            pickle.dump( self.cache, f )
        os.remove( self.cache_lockfile )


class SurePetFlapMixin( object ):
    """
    A mixin that implements introspection of data collected by SurePetFlapAPI.
    """

    # Added by A. Greulich
    def set_pet_profile( self, pet_id = None, name = None, profile = None, household_id = None ):
        """
        Set lock mode of a pet (3 is locked, 2 is free)
        """
        household_id = household_id or self.default_household
        if profile is None or type(profile) != int:
            raise ValueError('Please define a profile int value')
        if pet_id is None and name is None:
            raise ValueError('Please define pet_id or name')
        if pet_id is None:
            pet_id = self.get_pet_id_by_name(name)
        pet_id = int(pet_id)
        try:
            tag_id = self.household['pets'][pet_id]['tag_id']
            pet_name = self.household['pets'][pet_id]['name']
        except KeyError as e:
            raise SPAPIUnknownPet(str(e))
        device_id = self.household['default_flap']

        headers = self._create_header()
        data = {"profile": profile}
        url = '%s/%s/tag/%s' % (_URL_DEV, device_id, tag_id)
        response = self.s.put(url, headers=headers, json=data)
        if response.status_code == 401:
            self.update_authtoken(force=True)
            if 'headers' in kwargs and 'Authorization' in kwargs['headers']:
                kwargs['headers']['Authorization'] = 'Bearer ' + self.cache['AuthToken']
                response = self.s.post(_URL_AUTH, headers=headers, json=data)
            else:
                raise SPAPIException('Auth required but not present in header')

        response_data = response.json()
        return 'data' in response_data and 'profile' in response_data['data'] and \
               response_data['data']['profile'] == profile

    def print_timeline( self, pet_id = None, name = None, entry_type = None, household_id = None ):
        """
        Print timeline for a particular pet, specify entry_type to only get one
        direction.  Default household is used if not specified.
        """
        household_id = household_id or self.default_household
        if pet_id is None and name is None:
            raise ValueError('Please define pet_id or name')
        if pet_id is None:
            pet_id = self.get_pet_id_by_name(name)
        pet_id=int(pet_id)
        try:
            tag_id = self.household['pets'][pet_id]['tag_id']
            pet_name = self.household['pets'][pet_id]['name']
        except KeyError as e:
            raise SPAPIUnknownPet( str(e) )
        petdata = self.all_pet_timeline[household_id][pet_id]

        for movement in petdata:
            try:
                if entry_type is not None:
                    if movement['movements'][0]['tag_id'] == tag_id:
                        if movement['movements'][0]['direction'] == entry_type:
                            print(movement['movements'][0]['created_at'], pet_name, DIRECTION[movement['movements'][0]['direction']])
                else:
                    if movement['movements'][0]['tag_id'] == tag_id:
                        print(movement['movements'][0]['created_at'], pet_name, DIRECTION[movement['movements'][0]['direction']])
            except Exception as e:
                print(e)

    def locked( self, flap_id = None, household_id = None ):
        """
        Return whether door is locked or not.  Default household and flap used
        if not specified.
        """
        household_id = household_id or self.default_household
        household = self.households[household_id]
        if flap_id is None:
            flap_id = household['default_flap']
        lock_data = self.all_flap_status[household_id][flap_id]['locking']
        if lock_data['mode'] == LK_MOD.UNLOCKED:
            return False
        if lock_data['mode'] in [LK_MOD.LOCKED_IN, LK_MOD.LOCKED_OUT, LK_MOD.LOCKED_ALL,]:
            return True
        if lock_data['mode'] == LK_MOD.CURFEW:
            return lock_data['curfew']['locked']

    def lock_mode( self, flap_id = None, household_id = None ):
        """
        Returns a string describing the flap lock mode.  Default household and
        flap used if not specified.
        """
        lock = self.get_lock_mode( flap_id, household_id )
        if lock == LK_MOD.UNLOCKED:
            return 'Unlocked'
        elif lock == LK_MOD.LOCKED_IN:
            return 'Keep pets in'
        elif lock == LK_MOD.LOCKED_OUT:
            return 'Keep pets out'
        elif lock == LK_MOD.LOCKED_ALL:
            return 'Locked'
        elif lock == LK_MOD.CURFEW_UNKNOWN:
            return 'Curfew enabled but state unknown'
        elif lock == LK_MOD.CURFEW_LOCKED:
            return 'Locked with curfew'
        elif lock == LK_MOD.CURFEW_UNLOCKED:
            return 'Unlocked with curfew'

    def get_current_status( self, pet_id = None, name = None, household_id = None ):
        """
        Returns a string describing the last known movement of the pet.

        Note that because sometimes the chip reader fails to read the pet
        (especially if they exit too quickly), this function can indicate that
        they're inside when in fact they're outside.  The same limitation
        presumably applies to the official website and app.
        """
        if pet_id is None and name is None:
            raise ValueError('Please define pet_id or name')
        if pet_id is None:
            pet_id = self.get_pet_id_by_name(name)
        pet_id = int(pet_id)

        # Output modified by A. Greulich
        res = ""
        tag = self.get_pet_profile( pet_id, household_id )
        if tag == TAG.UNKNOWN:
            res = ""
        else:
            res = PROFILES[tag]

        loc = self.get_pet_location( pet_id, household_id )
        if loc == LOC.UNKNOWN:
            res += ' and currently Unknown'
        else:
            #Get last update
            res += ' and currently ' + INOUT_STATUS[loc]
        return res


class SurePetFlap( SurePetFlapMixin, SurePetFlapAPI ):
    """Class to take care of network communication with SurePet's products.

    See docstring for parent classes on how to use.  In particular, **please**
    do preserve property `cache` between instantiations in order to minimise
    wasted requests to Sure's servers.

    `cache` is guaranteed to be pickleable but not guaranteed to be
    serialisable as JSON.  How you store and retrieve it is up to you.

    """
    pass


class SPAPIException( Exception ):
    pass


class SPAPIReadOnly( SPAPIException ):
    pass


class SPAPICacheLocked( SPAPIException ):
    pass


class SPAPIAuthError( SPAPIException ):
    pass


class SPAPIUnitialised( SPAPIException ):
    pass


class SPAPIUnknownPet( SPAPIException ):
    pass
