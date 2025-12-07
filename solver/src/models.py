"""
Data models matching the Java entities from eval-platform.
These classes represent the core domain objects.
"""
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum
import uuid


class KitType(Enum):
    """Kit types with their properties matching KitType.java"""
    FIRST = ("A_FIRST_CLASS", 5.0, 200.0, 48)
    BUSINESS = ("B_BUSINESS", 3.0, 150.0, 36)
    PREMIUM_ECONOMY = ("C_PREMIUM_ECONOMY", 2.5, 100.0, 24)
    ECONOMY = ("D_ECONOMY", 1.5, 50.0, 12)
    
    def __init__(self, code: str, weight_kg: float, cost_eur: float, lead_time_hours: int):
        self.code = code
        self.weight_kg = weight_kg
        self.cost_eur = cost_eur
        self.lead_time_hours = lead_time_hours
    
    @property
    def weight(self) -> float:
        return self.weight_kg
    
    @property
    def cost(self) -> float:
        return self.cost_eur
    
    @property
    def lead_time(self) -> int:
        return self.lead_time_hours
    
    @staticmethod
    def from_column_name(col_name: str) -> 'KitType':
        """Convert CSV column names to KitType enum"""
        mapping = {
            'first': KitType.FIRST,
            'fc': KitType.FIRST,
            'business': KitType.BUSINESS,
            'bc': KitType.BUSINESS,
            'premium_economy': KitType.PREMIUM_ECONOMY,
            'pe': KitType.PREMIUM_ECONOMY,
            'economy': KitType.ECONOMY,
            'ec': KitType.ECONOMY
        }
        return mapping.get(col_name.lower())


@dataclass
class Airport:
    """Airport entity matching Airport.java"""
    id: str
    code: str
    name: str
    
    # Processing times (hours) per kit type
    first_processing_time: int
    business_processing_time: int
    premium_economy_processing_time: int
    economy_processing_time: int
    
    # Processing costs (EUR) per kit type
    first_processing_cost: float
    business_processing_cost: float
    premium_economy_processing_cost: float
    economy_processing_cost: float
    
    # Loading costs (EUR) per kit type
    first_loading_cost: float
    business_loading_cost: float
    premium_economy_loading_cost: float
    economy_loading_cost: float
    
    # Initial stock quantities
    initial_fc_stock: int
    initial_bc_stock: int
    initial_pe_stock: int
    initial_ec_stock: int
    
    # Capacity limits
    capacity_fc: int
    capacity_bc: int
    capacity_pe: int
    capacity_ec: int
    
    def get_processing_time(self, kit_type: KitType) -> int:
        """Get processing time for specific kit type"""
        mapping = {
            KitType.FIRST: self.first_processing_time,
            KitType.BUSINESS: self.business_processing_time,
            KitType.PREMIUM_ECONOMY: self.premium_economy_processing_time,
            KitType.ECONOMY: self.economy_processing_time
        }
        return mapping[kit_type]
    
    def get_processing_cost(self, kit_type: KitType) -> float:
        """Get processing cost for specific kit type"""
        mapping = {
            KitType.FIRST: self.first_processing_cost,
            KitType.BUSINESS: self.business_processing_cost,
            KitType.PREMIUM_ECONOMY: self.premium_economy_processing_cost,
            KitType.ECONOMY: self.economy_processing_cost
        }
        return mapping[kit_type]
    
    def get_loading_cost(self, kit_type: KitType) -> float:
        """Get loading cost for specific kit type"""
        mapping = {
            KitType.FIRST: self.first_loading_cost,
            KitType.BUSINESS: self.business_loading_cost,
            KitType.PREMIUM_ECONOMY: self.premium_economy_loading_cost,
            KitType.ECONOMY: self.economy_loading_cost
        }
        return mapping[kit_type]
    
    def get_initial_stock(self, kit_type: KitType) -> int:
        """Get initial stock for specific kit type"""
        mapping = {
            KitType.FIRST: self.initial_fc_stock,
            KitType.BUSINESS: self.initial_bc_stock,
            KitType.PREMIUM_ECONOMY: self.initial_pe_stock,
            KitType.ECONOMY: self.initial_ec_stock
        }
        return mapping[kit_type]
    
    def get_capacity(self, kit_type: KitType) -> int:
        """Get storage capacity for specific kit type"""
        mapping = {
            KitType.FIRST: self.capacity_fc,
            KitType.BUSINESS: self.capacity_bc,
            KitType.PREMIUM_ECONOMY: self.capacity_pe,
            KitType.ECONOMY: self.capacity_ec
        }
        return mapping[kit_type]
    
    @property
    def is_hub(self) -> bool:
        """Check if this is the hub airport"""
        return self.code == "HUB1"


@dataclass
class AircraftType:
    """Aircraft type entity matching AircraftType.java"""
    id: str
    type_code: str
    
    # Seat capacities
    first_class_seats: int
    business_seats: int
    premium_economy_seats: int
    economy_seats: int
    
    # Cost per kg per km (EUR)
    cost_per_kg_per_km: float
    
    # Kit storage capacities (different from seats!)
    first_class_kits_capacity: int
    business_kits_capacity: int
    premium_economy_kits_capacity: int
    economy_kits_capacity: int
    
    def get_kit_capacity(self, kit_type: KitType) -> int:
        """Get kit capacity for specific kit type"""
        mapping = {
            KitType.FIRST: self.first_class_kits_capacity,
            KitType.BUSINESS: self.business_kits_capacity,
            KitType.PREMIUM_ECONOMY: self.premium_economy_kits_capacity,
            KitType.ECONOMY: self.economy_kits_capacity
        }
        return mapping[kit_type]
    
    def get_seat_capacity(self, kit_type: KitType) -> int:
        """Get seat capacity for specific kit type"""
        mapping = {
            KitType.FIRST: self.first_class_seats,
            KitType.BUSINESS: self.business_seats,
            KitType.PREMIUM_ECONOMY: self.premium_economy_seats,
            KitType.ECONOMY: self.economy_seats
        }
        return mapping[kit_type]


@dataclass
class Flight:
    """Flight entity matching Flight.java"""
    id: str
    flight_number: str
    
    # Airport references (will be Airport objects)
    origin_airport_id: str
    destination_airport_id: str
    
    # Aircraft type references
    scheduled_aircraft_type_id: str
    actual_aircraft_type_id: str
    
    # Scheduled times
    scheduled_depart_day: int
    scheduled_depart_hour: int
    scheduled_arrival_day: int
    scheduled_arrival_hour: int
    
    # Actual times
    actual_arrival_day: int
    actual_arrival_hour: int
    
    # Distances
    distance: int
    actual_distance: int
    
    # Planned passengers
    planned_first_passengers: int
    planned_business_passengers: int
    planned_premium_economy_passengers: int
    planned_economy_passengers: int
    
    # Actual passengers
    actual_first_passengers: int
    actual_business_passengers: int
    actual_premium_economy_passengers: int
    actual_economy_passengers: int
    
    def get_planned_passengers(self, kit_type: KitType) -> int:
        """Get planned passenger count for specific kit type"""
        mapping = {
            KitType.FIRST: self.planned_first_passengers,
            KitType.BUSINESS: self.planned_business_passengers,
            KitType.PREMIUM_ECONOMY: self.planned_premium_economy_passengers,
            KitType.ECONOMY: self.planned_economy_passengers
        }
        return mapping[kit_type]
    
    def get_actual_passengers(self, kit_type: KitType) -> int:
        """Get actual passenger count for specific kit type"""
        mapping = {
            KitType.FIRST: self.actual_first_passengers,
            KitType.BUSINESS: self.actual_business_passengers,
            KitType.PREMIUM_ECONOMY: self.actual_premium_economy_passengers,
            KitType.ECONOMY: self.actual_economy_passengers
        }
        return mapping[kit_type]
    
    @property
    def scheduled_depart_hour_absolute(self) -> int:
        """Get absolute hour for scheduled departure"""
        return self.scheduled_depart_day * 24 + self.scheduled_depart_hour
    
    @property
    def scheduled_arrival_hour_absolute(self) -> int:
        """Get absolute hour for scheduled arrival"""
        return self.scheduled_arrival_day * 24 + self.scheduled_arrival_hour
    
    @property
    def actual_arrival_hour_absolute(self) -> int:
        """Get absolute hour for actual arrival"""
        return self.actual_arrival_day * 24 + self.actual_arrival_hour
    
    @property
    def flight_duration_hours(self) -> int:
        """Calculate flight duration in hours"""
        return self.scheduled_arrival_hour_absolute - self.scheduled_depart_hour_absolute
    
    @property
    def total_planned_passengers(self) -> int:
        """Total planned passengers across all classes"""
        return (self.planned_first_passengers + self.planned_business_passengers +
                self.planned_premium_economy_passengers + self.planned_economy_passengers)
    
    @property
    def total_actual_passengers(self) -> int:
        """Total actual passengers across all classes"""
        return (self.actual_first_passengers + self.actual_business_passengers +
                self.actual_premium_economy_passengers + self.actual_economy_passengers)


@dataclass
class RouteMetrics:
    """Pre-calculated metrics for a specific route"""
    origin_code: str
    destination_code: str
    
    # Flight statistics
    total_flights: int
    flights_per_week: float
    
    # Average metrics
    avg_distance: float
    avg_flight_duration: float
    avg_first_passengers: float
    avg_business_passengers: float
    avg_premium_economy_passengers: float
    avg_economy_passengers: float
    avg_total_passengers: float
    
    # Turnaround analysis
    min_turnaround_hours: Optional[int]
    max_turnaround_hours: Optional[int]
    avg_turnaround_hours: Optional[float]
    
    # Processing constraints
    processing_time_deficit: Dict[KitType, int]  # Negative if processing takes longer than turnaround
    
    # Cost metrics (will be calculated)
    avg_transport_cost_first: float = 0.0
    avg_transport_cost_business: float = 0.0
    avg_transport_cost_premium_economy: float = 0.0
    avg_transport_cost_economy: float = 0.0
    
    @property
    def avg_total_transport_cost(self) -> float:
        """Total average transport cost across all kit types"""
        return (self.avg_transport_cost_first + self.avg_transport_cost_business +
                self.avg_transport_cost_premium_economy + self.avg_transport_cost_economy)
    
    @property
    def is_tight_turnaround(self) -> bool:
        """Check if any kit type has processing time deficit"""
        return any(deficit < 0 for deficit in self.processing_time_deficit.values())
    
    @property
    def is_hub_route(self) -> bool:
        """Check if this is a HUB route"""
        return self.origin_code == "HUB1" or self.destination_code == "HUB1"


@dataclass
class FlightSchedulePattern:
    """Weekly flight schedule pattern"""
    route_key: tuple  # (origin, destination)
    scheduled_hour: int  # Hour of day (0-23)
    scheduled_arrival_hour: int
    arrival_next_day: bool
    distance_km: int
    
    # Days of week (1 = flies, 0 = doesn't fly)
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    
    @property
    def days_per_week(self) -> int:
        """Count how many days per week this flight operates"""
        return sum([self.monday, self.tuesday, self.wednesday, 
                   self.thursday, self.friday, self.saturday, self.sunday])
    
    @property
    def operates_on_day(self) -> list:
        """Get list of day names when this flight operates"""
        days = []
        if self.monday: days.append("Monday")
        if self.tuesday: days.append("Tuesday")
        if self.wednesday: days.append("Wednesday")
        if self.thursday: days.append("Thursday")
        if self.friday: days.append("Friday")
        if self.saturday: days.append("Saturday")
        if self.sunday: days.append("Sunday")
        return days
