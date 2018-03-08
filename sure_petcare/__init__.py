#!/usr/bin/python3
"""
Access the sure petcare access information
"""

import logging
import json
import requests
from datetime import datetime, timedelta
import os

class SurePetFlap(object):
    """Class to take care of cummunication with SurePet's products"""
    direction ={0:'Looked through',1:'Entered House',2:'Left House'}
    status = {1 : 'Inside', 2 : 'Outside'}
    def __init__(self, email_address=None, password=None, device_id=None):
        if email_address ==None or password==None or device_id==None:
            raise ValueError('Please provide, email, password and device id')
        self.debug=True
        self.Status={}
        self.pets={}
        self.s = requests.session()
        self.email_address = email_address
        self.password = password
        self.device_id = device_id        
        self.update()
        
    def update(self):
        self.update_authtoken()
        self.update_household_id()
        self.get_device_ids()
        self.get_pet_info()
        self.update_pet_status()
        self.flap_status = self.get_flap_status()
        self.router_status = self.get_router_status()
        self.household = self.get_housedata()
        self.curfew_status = [ i for i in self.household['data'] if i['type'] == 20 ]
        self.curfew_lock_info=json.loads(self.curfew_status[0]['data'])['locked']
    def locked(self):
        lock = self.flap_status['data']['locking']['mode']
        if lock == 0 :
            return False
        if lock == 1 or lock == 2 or lock ==3 :
            return True
        if lock == 4 :
            if self.curfew_lock_info :
                return True
            else:
                return False
    def lock_mode(self):
        lock = self.flap_status['data']['locking']['mode']
        if lock == 0:
            return 'Unlocked'
        elif lock == 1:
            return 'Keep pets in'
        elif lock == 2:
            return 'Keep pets out'
        elif lock == 3:
            return 'Locked'
        elif lock == 4:
            #We are in curfew mode, check log to see if in locked or unlocked.
            if self.curfew_lock_info :
                return 'Locked with curfew'
            else:
                return 'Unlocked with curfew'
    def print_timeline(self, petid, entry_type=None):
        petdata = self.petstatus[petid]
        for movement in petdata['data']:
            if movement['type'] == 20 or movement['type'] == 6:
                #type 20 == curfew
                #type 7 == Cat entry
                #type 6 == Manual change of entry
                continue
            try:
                if entry_type is not None:
                    if movement['movements'][0]['direction'] == entry_type:
                        print(movement['movements'][0]['created_at'], self.direction[movement['movements'][0]['direction']])
                else:
                    print(movement['movements'][0]['created_at'], self.direction[movement['movements'][0]['direction']])
            except Exception as e:
                print(e)
                print(i)
    def update_authtoken(self):
        """Get authentication token from servers"""
        data = '{"email_address":"' + self.email_address + '","password":"' + self.password + \
                '","device_id":"' + self.device_id + '"}'
        url = 'https://app.api.surehub.io/api/auth/login'
        headers=self.create_header(Content_length=88)
        response = self.s.post(url, headers=headers, data=data)
        response_data = json.loads(response.content.decode('utf-8'))
        self.AuthToken = response_data['data']['token']
    def update_household_id(self):
        params = (
            ('with[]', ['household', 'pet', 'users', 'timezone']),
        )
        url = 'https://app.api.surehub.io/api/household'
        headers=self.create_header(Authorization=self.AuthToken)
        response_household = self.s.get(url, headers=headers, params=params)
        response_household = json.loads(response_household.content.decode('utf-8'))
        self.HouseholdID = str(response_household['data'][0]['id'])
    def get_device_ids(self):
        params = (
            ('with[]', 'children'),
        )
        url = 'https://app.api.surehub.io/api/household/' + self.HouseholdID +'/device'
        response_children = self.get_data(url, params)
        for device in response_children['data']:
            if device['product_id'] == 3: # Catflap
                self.catflap_id = device['id']
            elif device['product_id'] == 1: # Router
                self.router_id = device['id']
    def get_pet_info(self):
        params = (
            ('with[]', ['photo', 'tag']),
        )
        url = 'https://app.api.surehub.io/api/household/' + self.HouseholdID + '/pet'
        response_pets = self.get_data(url, params)
        for pet in response_pets['data']:
            pet_id = pet['id']
            self.pets[pet_id]={}
            self.pets[pet_id]['tag_id']=pet['tag_id']
            self.pets[pet_id]['name']=pet['name']
            self.pets[pet_id]['household']=pet['household_id']
            if 'photo' in pet:
                self.pets[pet_id]['photo']=pet['photo']['location']
            else:
                self.pets[pet_id]['photo']=None
    def get_flap_status(self):
        url ='https://app.api.surehub.io/api/device/' + str(self.catflap_id) + '/status'
        response = self.get_data(url)
        return response
    def get_router_status(self):
        url = 'https://app.api.surehub.io/api/device/' + str(self.router_id) + '/status'
        response = self.get_data(url)
        return response
    def get_housedata(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        url = 'https://app.api.surehub.io/api/timeline/household/' + str(self.HouseholdID)
        response_housedata = self.get_data(url, params)
        return response_housedata
    def update_pet_status(self):
        params = (
            ('type', '0,3,6,7,12,13,14,17,19,20'),
        )
        petdata={}
        for pet_id in self.pets:
            url = 'https://app.api.surehub.io/api/timeline/pet/' + str(pet_id) + '/' + self.HouseholdID
            response = self.get_data(url, params=params)
            petdata[pet_id] = response
        self.petstatus=petdata
    def get_data(self, url, params=None, refresh_interval=3600):
        headers = None
        if url in self.Status:
            time_since_last =  datetime.now() - self.Status[url]['ts']
            if time_since_last.total_seconds() < refresh_interval: #Refresh every hour at least
                headers = self.create_header(Authorization=self.AuthToken, ETag=self.Status[url]['ETag'])
            else:
                self.debug_print('Refreshing data')
        if headers == None:
            self.Status[url]={}
            headers = self.create_header(Authorization=self.AuthToken)
        response = self.s.get(url, headers=headers, params=params)
        if response.status_code == 304:
            print('Got a 304')
            return self.Status[url]['LastData']
        self.Status[url]['LastData']  = json.loads(response.content.decode('utf-8'))
        self.Status[url]['ETag'] = response.headers['ETag'][1:-1]
        self.Status[url]['ts'] = datetime.now()
        return self.Status[url]['LastData']
    def find_id(self, name):
        for petid in pets:
            if self.pets[petid]['name'] == name:
                return petid
    def get_current_status(self, petid=None, name=None):
        if petid is None and name is None:
            raise ValueError('Please define petid or name')
        if petid is None:
            petid = self.find_id(name)
        petid=int(petid)
        if not int(petid) in self.petstatus:
            return 'Unknown'
        else:
            #Get last update
            for movement in self.petstatus[petid]['data']:
                if movement['type'] == 20 or movement['type'] == 6:
                    #type 20 == curfew
                    #type 7 == Cat entry
                    #type 6 == Manual change of entry
                    continue
                if movement['movements'][0]['direction'] != 0:
                    return self.status[movement['movements'][0]['direction']]
            return 'Unknown'
    def create_header(self, Content_length='0', Authorization=None, ETag=None):
        headers={'Host': 'app.api.surehub.io',
        'Connection': 'keep-alive',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://surepetcare.io',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 7.0; SM-G930F Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/64.0.3282.137 Mobile Safari/537.36',
        'Content-Type': 'application/json;charset=UTF-8',
        'Referer': 'https://surepetcare.io/',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'en-US,en-GB;q=0.9',
        'X-Requested-With': 'com.sureflap.surepetcare'}
        headers['Content-Length']=str(Content_length)
        if Authorization is not None:
            headers['Authorization']='Bearer ' + Authorization
        if ETag is not None:
            headers['If-None-Match'] = ETag
        return headers
    def debug_print(self, string):
        if self.debug:
            print(string)

def getmac():
    mac = None
    folders = os.listdir('/sys/class/net/')
    for interface in folders:
        if interface =='lo':
            continue
        try:
            mac = open('/sys/class/net/'+interface+'/address').readline()
        except Exception as e:
            print(e)
    return mac[:-1] #trim new line

def gen_device_id():
    mac = getmac()
    sum = 0 
    for i in mac:
        if i ==':' or i == '-':
            continue
        if ord(i) >= 48 and  ord(i) <= 58:
            sum +=int(i)
        elif ord(i) >= 97 and ord(i) <= 102:
            sum += 10 + ord(i)-97
        elif ord(i) >= 65 and ord(i) <= 80:
            sum += 10 + ord(i)-65
        sum = sum << 4
    sum = str(sum)[0:10]
    return sum
