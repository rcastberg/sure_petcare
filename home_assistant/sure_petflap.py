import logging
from datetime import timedelta
import json

import voluptuous as vol

from homeassistant.helpers.entity import Entity
import homeassistant.util as util
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from deps.sure_petcare import *

#REQUIREMENTS = ['sure_petcare']


_LOGGER = logging.getLogger(__name__)

CONF_device_id = 'device_id'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
})

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

    def __init__(self, username, password):
        """Initialize the sensor."""
        _LOGGER.debug('Initializing...')
        #guestimate, low voltage=1.0V/cell, need to measure low voltage battery
        self.LOW_BATTERY_VOLTAGE = 4.0 
        self.battery = [-1] *60
        self.battery[0] = 1 # Initialize average so we have a mean
        self.battery_pos = -1
        self.sure = SurePetFlap(email_address=username, password=password, device_id=gen_device_id())
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
    
    @util.Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        _LOGGER.debug('Returning current state...')
        flap_status = {}
        self.sure.update()
        for pet in  self.sure.pets:
            pet_status = self.sure.get_current_status(pet)
            flap_status[str(self.sure.pets[pet]['name'])]  = pet_status
        self.battery_pos = (self.battery_pos + 1) % len(self.battery) #Loop around
        self.battery[self.battery_pos] = int((self.sure.flap_status['data']['battery'] - self.LOW_BATTERY_VOLTAGE)/(6.0-self.LOW_BATTERY_VOLTAGE)*100)
        flap_status['avg_battery'] = int(self.mean([ i for i in self.battery if i > 0]))
        flap_status['battery'] = self.battery[self.battery_pos]
        flap_status['flap_online']  = self.sure.flap_status['data']['online'] 
        flap_status['hub_online'] =  self.sure.router_status['data']['online']
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
