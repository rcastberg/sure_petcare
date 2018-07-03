import logging
from datetime import timedelta
import json

def is_hass_component():
    try:
        import homeasssistant
        return True
    except ImportError:
        return False

if is_hass_component():
    from homeassistant.helpers.entity import Entity
    from homeassistant.util import Throttle
    from homeassistant.components.sensor import PLATFORM_SCHEMA
    from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
    import homeassistant.helpers.config_validation as cv

    from deps.sure_petcare import SurePetFlap
    from deps.sure_petcare.utils import gen_device_id

    import voluptuous as vol

    PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    })
else:
    # Assume not running within home assistant.  This *does* mean that you
    # won't be able to run this test script if you have homeassistant
    # installed but, if you do, you're probably running (or can run) this
    # component from within hass anyway.
    from sure_petcare import SurePetFlap
    from sure_petcare.utils import gen_device_id

    # dummy dependencies
    class Entity( object ):
        pass

    def Throttle( *args, **kwargs ):
        def decorator( f ):
            return f
        return decorator


#REQUIREMENTS = ['sure_petcare']


_LOGGER = logging.getLogger(__name__)

CONF_device_id = 'device_id'

SCAN_INTERVAL = timedelta(seconds=300)
MIN_TIME_BETWEEN_SCANS = timedelta(seconds=600)
MIN_TIME_BETWEEN_FORCED_SCANS = timedelta(seconds=120)

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the sensor platform."""
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    add_devices([SurePetConnect(username, password)])


class SurePetConnect(Entity):
    """Representation of a Sensor."""

    def __init__(self, username, password, **kwargs):
        """Initialize the sensor."""
        _LOGGER.debug('Initializing...')
        # 1.25V is a fairly conservative guess for alkalines.  If you use
        # rechargeables, you may need to change this.
        self.FULL_BATTERY_VOLTAGE = 1.6 # volts
        self.LOW_BATTERY_VOLTAGE = 1.25 # volts
        self.battery = [-1] *60
        self.battery[0] = 1 # Initialize average so we have a mean
        self.battery_pos = -1
        self.sure = SurePetFlap(email_address=username, password=password, device_id=gen_device_id(), **kwargs)
        self._state = None
        self._attributes = []
        self.update()

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'SurePet Connect'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return ''
    
    @Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        _LOGGER.debug('Returning current state...')
        flap_status = {}
        with self.sure:
            # Update only data required
            self.sure.update_authtoken()
            self.sure.update_households()
            self.sure.update_device_ids()
            self.sure.update_pet_info()
            self.sure.update_pet_status()
            self.sure.update_flap_status()
            self.sure.update_router_status()
        for pet in self.sure.pets:
            pet_status = self.sure.get_current_status(pet)
            flap_status[str(self.sure.pets[pet]['name'])]  = pet_status
        self.battery_pos = (self.battery_pos + 1) % len(self.battery) #Loop around
        # NB: Units have changed.  Earlier versions reported the raw voltage
        #     direct from the Sure backend which was the sum of the four
        #     batteries.  The current API reports voltage per battery, making
        #     it easier to set thresholds based on battery chemistry.
        bat_left = self.sure.battery - self.LOW_BATTERY_VOLTAGE
        bat_full = self.FULL_BATTERY_VOLTAGE - self.LOW_BATTERY_VOLTAGE
        self.battery[self.battery_pos] = int(bat_left/bat_full*100)
        flap_status['avg_battery'] = int(self.mean([ i for i in self.battery if i > 0]))
        flap_status['battery'] = self.battery[self.battery_pos]
        flap_status['flap_online']  = self.sure.flap_status[self.sure.default_flap]['online']
        flap_status['hub_online'] =  self.sure.router_status[self.sure.default_router]['online']
        flap_status['lock_status'] = self.sure.lock_mode()
        flap_status['locked'] = self.sure.locked()
        _LOGGER.debug('State: ' + str(flap_status))
        self._state = json.dumps(flap_status)
        self._attributes = flap_status

    @property
    def state_attributes(self):
        """Return the attributes of the entity.

           Provide the parsed JSON data (if any).
        """

        return self._attributes
    
    def mean(self, numbers):
        return float(sum(numbers)) / max(len(numbers), 1)
