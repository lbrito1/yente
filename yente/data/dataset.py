from pathlib import Path
from banal import as_bool
from normality import slugify
from datetime import datetime
from typing import AsyncGenerator, Dict, Optional, Any
from nomenklatura.dataset import Dataset as NKDataset
from nomenklatura.dataset import DataCatalog
from nomenklatura.dataset.util import type_check, type_require
from nomenklatura.util import iso_to_version, datetime_iso
from followthemoney import model
from followthemoney.types import registry
from followthemoney.namespace import Namespace

from yente.data.entity import Entity
from yente.logs import get_logger
from yente.data.loader import get_url_path, load_json_lines

log = get_logger(__name__)
BOOT_TIME = datetime_iso(datetime.utcnow())


class Dataset(NKDataset):
    def __init__(self, catalog: DataCatalog["Dataset"], data: Dict[str, Any]):
        name = data["name"]
        norm_name = slugify(name, sep="_")
        if name != norm_name:
            raise ValueError("Invalid dataset name %r (try: %r)" % (name, norm_name))
        super().__init__(catalog, data)

        if self.version is None:
            ts = data.get("last_export", BOOT_TIME)
            self.version = iso_to_version(ts) or "static"

        self.load = as_bool(data.get("load"), True)
        self.entities_url = self._get_entities_url(data)
        namespace = as_bool(data.get("namespace"), False)
        self.ns = Namespace(self.name) if namespace else None

    def _get_entities_url(self, data: Dict[str, Any]) -> Optional[str]:
        if "entities_url" in data:
            return type_require(registry.url, data.get("entities_url"))
        path = type_check(registry.string, data.get("path"))
        if path is not None:
            return Path(path).resolve().as_uri()
        resource_name = type_check(registry.string, data.get("resource_name"))
        resource_type = type_check(registry.string, data.get("resource_type"))
        for resource in self.resources:
            if resource.url is None:
                continue
            if resource_name is not None and resource.name == resource_name:
                return resource.url
            if resource_type is not None and resource.mime_type == resource_type:
                return resource.url
        return None

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["load"] = self.load
        data["entities_url"] = self.entities_url
        data["namespace"] = self.ns is not None
        return data

    async def entities(self) -> AsyncGenerator[Entity, None]:
        if not self.load:
            return
        if self.entities_url is None:
            log.warning("Cannot identify resource with FtM entities", dataset=self.name)
            return
        datasets = set(self.dataset_names)
        base_name = f"{self.name}-{self.version}.json"
        data_path = await get_url_path(self.entities_url, base_name)
        async for data in load_json_lines(data_path):
            entity = Entity.from_dict(model, data)
            entity.datasets = entity.datasets.intersection(datasets)
            if not len(entity.datasets):
                entity.datasets.add(self.name)
            if self.ns is not None:
                entity = self.ns.apply(entity)
            yield entity
