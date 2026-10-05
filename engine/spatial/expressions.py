"""Typed scalar distance over an existing coordinate mapping."""

from dataclasses import dataclass

from engine.catalog import DataType
from engine.errors import ValidationError
from engine.operators.expressions import BoundExpression, Expression
from engine.operators.rows import ColumnReference, RowLayout

from .geometry import Metric, Point, distance


@dataclass(frozen=True, slots=True)
class BoundDistance(BoundExpression):
    latitude_position: int
    longitude_position: int
    center: Point
    metric: Metric

    @property
    def data_type(self):
        return DataType.FLOAT

    def evaluate(self, values):
        point = Point(values[self.latitude_position], values[self.longitude_position])
        return distance(point, self.center, self.metric)


@dataclass(frozen=True, slots=True)
class Distance(Expression):
    latitude: ColumnReference
    longitude: ColumnReference
    center: Point
    metric: Metric

    def bind(self, layout: RowLayout) -> BoundDistance:
        latitude, longitude = layout.field(self.latitude), layout.field(self.longitude)
        if latitude.data_type is not DataType.FLOAT or longitude.data_type is not DataType.FLOAT:
            raise ValidationError("Distance coordinates must be FLOAT")
        return BoundDistance(latitude.position, longitude.position, self.center, self.metric)
