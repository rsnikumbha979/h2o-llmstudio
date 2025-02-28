import logging
from dataclasses import dataclass, fields
from typing import Any, List, Optional, Sequence, Set, Tuple

from llm_studio.src import possible_values
from llm_studio.src.nesting import Dependency, Nesting
from llm_studio.src.order import Order

logger = logging.getLogger(__name__)


def _get_bases_below_parent(cls: type, parent: type, bases=None) -> Set[type]:
    if bases is None:
        bases = set()

    if parent not in cls.__bases__:
        for base in cls.__bases__:
            bases.update(_get_bases_below_parent(base, parent, bases))
    else:
        # don't support multiple inheritance when
        # inherting directly from the parent
        assert len(cls.__bases__) == 1

        bases.add(cls)

    return bases


@dataclass
class DefaultConfig:
    """
    Template for any configuration file
    """

    def __post_init__(self):
        self._possible_values = {k: None for k in self.__dict__}
        self._visibility = {k: 0 for k in self.__dict__}

        # go up the class hierarchy until we are one below the `DefaultConfig`
        bases = _get_bases_below_parent(self.__class__, DefaultConfig)

        # there must be exactly one unique class up the class hierarchy
        # which inherits directly from the `DefaultConfig`
        assert len(bases) == 1
        base = next(iter(bases))

        # initialize the order to the fields this class has
        self._order = Order([field.name for field in fields(base)])

        # initialize nesting dependencies
        self._nesting = Nesting()

    def _get_possible_values(
        self, field: str, value: Any, type_annotation: type, mode: str, dataset_fn=None
    ) -> Optional[Tuple[Optional[possible_values.Value], Any]]:
        """
        Returns a set of possible values for the field provided, and the current value.

        Args:
            field: the field
            value: the preliminary value of the field.
            type_annotation: Type Annotation of the field.
            mode: current mode, one of {"train", "test", "predict"}.
            dataset_fn: A function returning a tuple (dataset, value). Will be called
                if the possible values depend on the dataset.

        Returns:
            Possible values for the field, the current value.
        """

        poss_values = self._possible_values.get(field, None)

        if isinstance(poss_values, possible_values.DatasetValue):
            if dataset_fn is None:
                raise ValueError(
                    f"{poss_values} needs a dataset to compute possible values!\n"
                    "`dataset_fn` must be provided."
                )

            dataset, value = dataset_fn(field, value)
            poss_values, value = poss_values.get_value(
                dataset=dataset, value=value, type_annotation=type_annotation, mode=mode
            )
        elif isinstance(poss_values, Sequence):
            if all(isinstance(x, (float, int)) for x in poss_values):
                poss_values = possible_values.Number(
                    min=poss_values[0], max=poss_values[1], step=poss_values[2]
                )
            elif all(isinstance(x, str) for x in poss_values):
                poss_values = possible_values.String(tuple(poss_values))
            else:
                raise ValueError(
                    f"Could not interpret {poss_values} as any possible value class."
                )

        return poss_values, value

    def _get_tooltips(self, field: str, predict: bool = False) -> Optional[str]:
        """
        Returns a tooltip for the field provided
        """
        return None

    def _get_visibility(self, field: str) -> Optional[int]:
        """Returns a visibility level for the field provided.
         0 -- visible in the Wave app
        -1 -- not visible in the Wave App
        -2 -- visible in Dataset Import, but not visible in Create Experiment
        """

        return self._visibility.get(field, None)

    def _get_nesting_triggers(self) -> List[str]:
        """Returns a List of keys other elements are depending on"""

        return self._nesting.triggers

    def _get_nesting_dependencies(self, key: str) -> List[Dependency]:
        """Returns a all dependencies for a given key"""

        if key in self._nesting.dependencies:
            dependencies = self._nesting.dependencies[key]
        else:
            dependencies = None
        return dependencies

    def _get_order(self, warn_if_unset=True) -> List[str]:
        """
        Returns the order in which to show the keys in the config.

        Args:
            warn_if_unset: Whether to log a warning if order is unset for multiple keys.

        Returns:
            A list of the same length and with same elements as `self.__dict__.keys()`.
        """

        keys = self.__dict__.keys()

        ordered_keys = [key for key in self._order if key in keys]
        unordered_keys = list(set(keys) - set(ordered_keys))

        unordered_ui_keys = [
            key
            for key in unordered_keys
            if not (key.startswith("_") or self._get_visibility(key) == -1)
        ]

        # warn if there is more than one key without order.
        # one is not problematic since it will just always be last
        if warn_if_unset and len(unordered_ui_keys) > 1:
            logger.warning(f"No order set for keys: {unordered_ui_keys}.")

        return ordered_keys + unordered_keys

    @classmethod
    def get_annotations(cls):
        """Returns type annotations through all the Parent config classes"""

        d = {}
        for c in cls.mro()[::-1]:
            try:
                d.update(**c.__annotations__)
            except AttributeError:
                # object, at least, has no __annotations__ attribute.
                pass
        return d

    @classmethod
    def from_dict(cls, d: dict):
        """Creates a config object from a dictionary"""
        d_filtered = {k: v for k, v in d.items() if k in cls.get_annotations()}
        if len(d) != len(d_filtered):
            logger.warning(
                f"Keys {set(d.keys()) - set(d_filtered.keys())} are not in the config."
            )
        return cls(**d_filtered)  # mypy: ignore
