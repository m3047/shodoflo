#!/usr/bin/python3
# Copyright (c) 2019,2023 by Fred Morris Tacoma WA
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Things useful for dealing with Redis."""

import ipaddress

class ClientArtifact(object):
    """Base class for artifacts."""
    
    METADATA_FOR = dict(
        targets     = lambda self: str(self.client_address),
        clients     = lambda self: str(self.client_address),
        types       = lambda self: str(type(self)).split("'")[1].split('.')[-1].replace('Artifact',''),
        ports       = lambda self: str(self.remote_port)
    )
    
    def __init__(self, k=None, v=None):
        if k is None:
            return
        self.extract_key_data(k.split(';'))
        self.extract_value_data(v)
        return
    
    def extract_key_data(self,k):
        """Extract information from the key.
        
        Information potentially includes:
        
        * client address
        * remote address
        * remote port
        * rname (right hand side name)
        * oname (left hand side name)
        
        This method needs to be implemented by the subclass.
        """
        pass
    
    def extract_value_data(self,v):
        """Extract information from the value associated with the key.
        
        Information potentially includes:
        
        * list of onames
        * count
        
        This method needs to be implemented by the subclass.
        """
        pass
    
    def metadata_for(self, k):
        """Return metadata for a metadata key.
        
        Depending on whether or not this is a merged artifact, it may or may not have
        a metadata attribute, with data generated by calling this function previously.
        """
        if hasattr(self, 'metadata'):
            return self.metadata.get(k, set())
        md = set()
        if k in self.METADATA_TYPES:
            md.add(self.METADATA_FOR[k](self))
        return md
    
    def append_to_mapping(self, k, mapping):
        if k not in mapping:
            mapping[k] = []
        mapping[k].append(self)
        return
    
    def is_targeted(self, target):
        return target is None or self.client_address in target
    
class CounterArtifact(ClientArtifact):
    """The associated value is a count."""
    def extract_value_data(self,v):
        self.count = int(v)
        return

class ListArtifact(ClientArtifact):
    """The associated value is a list.
    
    It's always a list of onames (left hand side values). Or in other words
    it is the reverse of normal DNS lookup.
    """
    def extract_value_data(self,v):
        self.onames = [ oname for oname in v.split(';') if oname ]

    def update_origins(self, origin_type, origin_list):
        """Update origin_list.
        
        origin_list is a list of keys into mappings. mappings is updated by
        update_mappings().
        """
        if origin_type not in self.ORIGIN_FOR:
            return
        for name in self.onames:
            self.append_to_mapping(name, origin_list)
        return
    
    def update_fqdn_mappings(self,mappings):
        for name in self.onames:
            self.append_to_mapping(name, mappings)
        return
    
    def update_mappings(self, origin_type, mappings):
        if origin_type not in self.MAPPING_FOR:
            return
        if origin_type == 'address':
            self.update_address_mappings(mappings)
        else:           # 'fqdn'
            self.update_fqdn_mappings(mappings)
        return

    def onames_as_list(self):
        """Converts onames property from a set to a list, returning the instance."""
        self.onames = list(self.onames)
        return self

class DNSArtifact(ListArtifact):
    """A DNS artifact."""

    CLIENT_ADDR = 0
    REMOTE_ADDR = 1
    
    ORIGIN_FOR = {'fqdn'}
    MAPPING_FOR = {'address','fqdn'}
    METADATA_TYPES = {'clients','types'}
    
    def extract_key_data(self,k):
        self.client_address = ipaddress.ip_address(k[self.CLIENT_ADDR])
        self.remote_address = ipaddress.ip_address(k[self.REMOTE_ADDR])
        return

    # update_origins() declared in ListArtifact.
    
    # update_mappings() and update_fqdn_mappings() declared in ListArtifact.
    
    def update_address_mappings(self,mappings):
        self.append_to_mapping(str(self.remote_address), mappings)
        return
    
    def children(self, origin_type, target):
        targeted = self.is_targeted(target)
        if origin_type == 'address':
            return [ (oname, targeted) for oname in self.onames ]
        else:           # fqdn
            return [(str(self.remote_address), targeted)]
    
    @staticmethod
    def merge(items, target):
        """Note that all items in the list will be of the same type.
        
        The caller also arranges that the items are instances of this class.
        """
        item = items.pop()
        merged = {}
        k = str(item.remote_address)
        merged[k] = item.copy(set)
        for item in items:
            k = str(item.remote_address)
            if k not in merged:
                merged[k] = item.copy(set)
                continue
            if item.is_targeted(target):
                merged[k].client_address = item.client_address
            merged[k].onames |= set(item.onames)
            for t in item.METADATA_TYPES:
                merged[k].metadata[t] |= item.metadata_for(t)
        return [ artifact.onames_as_list() for artifact in merged.values() ]
    
    def copy(self, onames_type=list):
        new = DNSArtifact()
        new.client_address = self.client_address
        new.remote_address = self.remote_address
        new.onames = onames_type(self.onames)
        new.metadata = { t:self.metadata_for(t) for t in self.METADATA_TYPES }
        return new

class CNAMEArtifact(ListArtifact):
    """A CNAME artifact."""

    CLIENT_ADDR = 0
    RNAME = 1
    
    ORIGIN_FOR = {'fqdn'}
    MAPPING_FOR = {'address','fqdn'}
    METADATA_TYPES = {'clients','types'}
    
    def extract_key_data(self,k):
        self.client_address = ipaddress.ip_address(k[self.CLIENT_ADDR])
        self.rname = k[self.RNAME]
        return
    
    @property
    def name(self):
        return self.rname

    # update_origins() declared in ListArtifact.

    # update_mappings() and update_fqdn_mappings() declared in ListArtifact.

    def update_address_mappings(self,mappings):
        self.append_to_mapping(self.rname, mappings)
        return

    def children(self, origin_type, target):
        targeted = self.is_targeted(target)
        if origin_type == 'address':
            return [ (oname, targeted) for oname in self.onames ]
        else:           # fqdn
            return [(self.rname, targeted)]

    @staticmethod
    def merge(items, target):
        """Note that all items in the list will be of the same type.
        
        The caller also arranges that the items are instances of this class.
        """
        item = items.pop()
        merged = {}
        k = item.rname
        merged[k] = item.copy(set)
        for item in items:
            k = item.rname
            if k not in merged:
                merged[k] = item.copy(set)
                continue
            if item.is_targeted(target):
                merged[k].client_address = item.client_address
            merged[k].onames |= set(item.onames)
            for t in item.METADATA_TYPES:
                merged[k].metadata[t] |= item.metadata_for(t)
        return [ artifact.onames_as_list() for artifact in merged.values() ]
    
    def copy(self, onames_type=list):
        new = CNAMEArtifact()
        new.client_address = self.client_address
        new.rname = self.rname
        new.onames = onames_type(self.onames)
        new.metadata = { t:self.metadata_for(t) for t in self.METADATA_TYPES }
        return new
    
class NXDOMAINArtifact(CounterArtifact):
    """An FQDN for which DNS resolution failed."""

    CLIENT_ADDR = 0
    ONAME = 1
    
    ORIGIN_FOR = {'fqdn'}
    MAPPING_FOR = {'fqdn'}
    METADATA_TYPES = {'clients','types'}
    
    def extract_key_data(self,k):
        self.client_address = ipaddress.ip_address(k[self.CLIENT_ADDR])
        self.oname = k[self.ONAME]
        return
    
    @property
    def name(self):
        return self.oname

    def update_origins(self, origin_type, origin_list):
        """Update origin_list.
        
        origin_list is a list of keys into mappings. mappings is updated by
        update_mappings().
        """
        if origin_type not in self.ORIGIN_FOR:
            return
        self.append_to_mapping(self.oname, origin_list)
        return
    
    def update_mappings(self, origin_type, mappings):
        if origin_type not in self.MAPPING_FOR:
            return
        self.append_to_mapping(self.oname, mappings)
        return

    def children(self, origin_type, target):
        if origin_type == 'fqdn':
            return [(self.oname, self.is_targeted(target))]
        else:           # fqdn
            return []

    @staticmethod
    def merge(items, target):
        """Note that all items in the list will be of the same type.
        
        The caller also arranges that the items are instances of this class.
        """
        item = items.pop()
        merged = {}
        k = item.oname
        merged[k] = item.copy()
        for item in items:
            k = item.oname
            if k not in merged:
                merged[k] = item.copy()
                continue
            if item.is_targeted(target):
                merged[k].client_address = item.client_address
            merged[k].count += item.count
            for t in item.METADATA_TYPES:
                merged[k].metadata[t] |= item.metadata_for(t)
        return merged.values()
    
    def copy(self):
        new = NXDOMAINArtifact()
        new.client_address = self.client_address
        new.oname = self.oname
        new.count = self.count
        new.metadata = { t:self.metadata_for(t) for t in self.METADATA_TYPES }
        return new
    
class NetflowArtifact(CounterArtifact):
    """A Packet Capture artifact."""

    CLIENT_ADDR = 0
    REMOTE_ADDR = 1
    REMOTE_PORT = 2
    
    ORIGIN_FOR = {'address'}
    MAPPING_FOR = set()
    METADATA_TYPES = {'clients','types','ports'}
    
    def extract_key_data(self,k):
        self.client_address = ipaddress.ip_address(k[self.CLIENT_ADDR])
        self.remote_address = ipaddress.ip_address(k[self.REMOTE_ADDR])
        self.remote_port = k[self.REMOTE_PORT]
        return

    def update_origins(self, origin_type, origin_list):
        """Update origin_list.
        
        origin_list is a list of keys into mappings. mappings is updated by
        update_mappings().
        """
        if origin_type not in self.ORIGIN_FOR:
            return
        self.append_to_mapping(str(self.remote_address), origin_list)
        return
    
    def update_mappings(self, origin_type, mappings):
        """NetflowArtifact is not a mapping type for any origin."""
        #if origin_type not in self.MAPPING_FOR:
            #return
        return
    
    def children(self, origin_type, target):
        return []

    @staticmethod
    def merge(items, target):
        """Note that all items in the list will be of the same type.
        
        The caller also arranges that the items are instances of this class.
        """
        item = items.pop()
        merged = {}
        k = '{}+{}'.format(item.remote_address, item.remote_port)
        merged[k] = item.copy()
        for item in items:
            k = '{}+{}'.format(item.remote_address, item.remote_port)
            if k not in merged:
                merged[k] = item.copy()
                continue
            if item.is_targeted(target):
                merged[k].client_address = item.client_address
            merged[k].count += item.count
            for t in item.METADATA_TYPES:
                merged[k].metadata[t] |= item.metadata_for(t)
        return merged.values()
    
    def copy(self):
        new = type(self)()
        new.client_address = self.client_address
        new.remote_address = self.remote_address
        new.remote_port = self.remote_port
        new.count = self.count
        new.metadata = { t:self.metadata_for(t) for t in self.METADATA_TYPES }
        return new

class ReconArtifact(NetflowArtifact):
    """(Possible) Reconnaissance Artifact.
    
    These are a special case of netflow, because the sense of things is reverse. We
    want to list the client in the visible listing, and the targets (remotes) in the
    rollover.
    """
    REVERSED_METADATA_TYPES = {'targets','types','ports'}
    def reversed(self):
        """Create a new ReconArtifact with the client and remote reversed."""
        new = type(self)()
        new.client_address = self.remote_address
        new.remote_address = self.client_address
        new.remote_port = self.remote_port
        new.count = self.count
        new.METADATA_TYPES = self.REVERSED_METADATA_TYPES
        new.metadata = { t:new.metadata_for(t) for t in self.REVERSED_METADATA_TYPES }
        return new
        

class RSTArtifact(ReconArtifact):
    """TCP RST artifact.
    
    A special type of netflow artifact which can indicate an attempt to connect to
    a TCP port which is not listening (a probing attempt). As such it is also captured
    between two addresses on the "our" network.
    """
    pass

class ICMPArtifact(ReconArtifact):
    """ICMP Unreachable artifact.
    
    A special type of netflow artifact which can indicate an attempt to connect to
    a UDP port which is not listening (a probing attempt). As such it is also captured
    between two addresses on the "our" network.
    """
    pass

ARTIFACT_MAPPER = dict(
        dns     = DNSArtifact,
        cname   = CNAMEArtifact,
        nx      = NXDOMAINArtifact,
        flow    = NetflowArtifact,
        rst     = RSTArtifact,
        icmp    = ICMPArtifact
    )

