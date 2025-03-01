#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import datetime
import json
from typing import Tuple, Optional

from pyspark.sql.types import DateType, Row, StructType

__all__ = ["GroupStateImpl", "GroupStateTimeout"]


class GroupStateTimeout:
    NoTimeout: str = "NoTimeout"
    ProcessingTimeTimeout: str = "ProcessingTimeTimeout"
    EventTimeTimeout: str = "EventTimeTimeout"


class GroupStateImpl:
    NO_TIMESTAMP: int = -1

    def __init__(
        self,
        # JVM Constructor
        optionalValue: Row,
        batchProcessingTimeMs: int,
        eventTimeWatermarkMs: int,
        timeoutConf: str,
        hasTimedOut: bool,
        watermarkPresent: bool,
        # JVM internal state.
        defined: bool,
        updated: bool,
        removed: bool,
        timeoutTimestamp: int,
        # Python internal state.
        keyAsUnsafe: bytes,
        valueSchema: StructType,
    ) -> None:
        self._keyAsUnsafe = keyAsUnsafe
        self._value = optionalValue
        self._batch_processing_time_ms = batchProcessingTimeMs
        self._event_time_watermark_ms = eventTimeWatermarkMs

        assert timeoutConf in [
            GroupStateTimeout.NoTimeout,
            GroupStateTimeout.ProcessingTimeTimeout,
            GroupStateTimeout.EventTimeTimeout,
        ]
        self._timeout_conf = timeoutConf

        self._has_timed_out = hasTimedOut
        self._watermark_present = watermarkPresent

        self._defined = defined
        self._updated = updated
        self._removed = removed
        self._timeout_timestamp = timeoutTimestamp
        # Python internal state.
        self._old_timeout_timestamp = timeoutTimestamp

        self._value_schema = valueSchema

    @property
    def exists(self) -> bool:
        return self._defined

    @property
    def get(self) -> Tuple:
        if self.exists:
            return tuple(self._value)
        else:
            raise ValueError("State is either not defined or has already been removed")

    @property
    def getOption(self) -> Optional[Tuple]:
        if self.exists:
            return tuple(self._value)
        else:
            return None

    @property
    def hasTimedOut(self) -> bool:
        return self._has_timed_out

    # NOTE: this function is only available to PySpark implementation due to underlying
    # implementation, do not port to Scala implementation!
    @property
    def oldTimeoutTimestamp(self) -> int:
        return self._old_timeout_timestamp

    def update(self, newValue: Tuple) -> None:
        if newValue is None:
            raise ValueError("'None' is not a valid state value")

        self._value = Row(*newValue)
        self._defined = True
        self._updated = True
        self._removed = False

    def remove(self) -> None:
        self._defined = False
        self._updated = False
        self._removed = True

    def setTimeoutDuration(self, durationMs: int) -> None:
        if isinstance(durationMs, str):
            # TODO(SPARK-40437): Support string representation of durationMs.
            raise ValueError("durationMs should be int but get :%s" % type(durationMs))

        if self._timeout_conf != GroupStateTimeout.ProcessingTimeTimeout:
            raise RuntimeError(
                "Cannot set timeout duration without enabling processing time timeout in "
                "applyInPandasWithState"
            )

        if durationMs <= 0:
            raise ValueError("Timeout duration must be positive")
        self._timeout_timestamp = durationMs + self._batch_processing_time_ms

    # TODO(SPARK-40438): Implement additionalDuration parameter.
    def setTimeoutTimestamp(self, timestampMs: int) -> None:
        if self._timeout_conf != GroupStateTimeout.EventTimeTimeout:
            raise RuntimeError(
                "Cannot set timeout duration without enabling processing time timeout in "
                "applyInPandasWithState"
            )

        if isinstance(timestampMs, datetime.datetime):
            timestampMs = DateType().toInternal(timestampMs)

        if timestampMs <= 0:
            raise ValueError("Timeout timestamp must be positive")

        if (
            self._event_time_watermark_ms != GroupStateImpl.NO_TIMESTAMP
            and timestampMs < self._event_time_watermark_ms
        ):
            raise ValueError(
                "Timeout timestamp (%s) cannot be earlier than the "
                "current watermark (%s)" % (timestampMs, self._event_time_watermark_ms)
            )

        self._timeout_timestamp = timestampMs

    def getCurrentWatermarkMs(self) -> int:
        if not self._watermark_present:
            raise RuntimeError(
                "Cannot get event time watermark timestamp without setting watermark before "
                "applyInPandasWithState"
            )
        return self._event_time_watermark_ms

    def getCurrentProcessingTimeMs(self) -> int:
        return self._batch_processing_time_ms

    def __str__(self) -> str:
        if self.exists:
            return "GroupState(%s)" % (self.get,)
        else:
            return "GroupState(<undefined>)"

    def json(self) -> str:
        return json.dumps(
            {
                # Constructor
                "optionalValue": None,  # Note that optionalValue will be manually serialized.
                "batchProcessingTimeMs": self._batch_processing_time_ms,
                "eventTimeWatermarkMs": self._event_time_watermark_ms,
                "timeoutConf": self._timeout_conf,
                "hasTimedOut": self._has_timed_out,
                "watermarkPresent": self._watermark_present,
                # JVM internal state.
                "defined": self._defined,
                "updated": self._updated,
                "removed": self._removed,
                "timeoutTimestamp": self._timeout_timestamp,
            }
        )
