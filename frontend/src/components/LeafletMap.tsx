import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Coordinate, SpatialPoint, SpatialTable } from "../types";

interface Props {
  table: SpatialTable;
  points: SpatialPoint[];
  hitIds: Set<string>;
  center: Coordinate;
  overlay: Coordinate[];
  draft: Coordinate[];
  busy: boolean;
  onChoose: (point: Coordinate) => void;
}

export default function LeafletMap(props: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<L.TileLayer | null>(null);
  const layers = useRef<L.LayerGroup | null>(null);
  const current = useRef(props);
  current.current = props;
  const [tileError, setTileError] = useState(false);

  useEffect(() => {
    if (host.current === null) return;
    const instance = L.map(host.current, { minZoom: 7, maxZoom: 19, scrollWheelZoom: true })
      .setView(current.current.table.conventions.origin, 12);
    map.current = instance;
    const background = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(instance);
    tiles.current = background;
    background.on("tileerror", () => setTileError(true));
    layers.current = L.layerGroup().addTo(instance);
    L.control.scale({ imperial: false }).addTo(instance);
    instance.on("click", (event: L.LeafletMouseEvent) => {
      if (!current.current.busy) current.current.onChoose([event.latlng.lat, event.latlng.lng]);
    });
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Enter" && event.target === host.current && !current.current.busy) {
        event.preventDefault();
        const point = instance.getCenter();
        current.current.onChoose([point.lat, point.lng]);
      }
    };
    host.current.addEventListener("keydown", keyboard);
    const observer = new ResizeObserver(() => instance.invalidateSize({ pan: false }));
    observer.observe(host.current);
    const container = host.current;
    return () => {
      observer.disconnect(); container.removeEventListener("keydown", keyboard);
      instance.remove(); map.current = null; layers.current = null; tiles.current = null;
    };
  }, []);

  useEffect(() => {
    map.current?.setView(props.table.conventions.origin, 12, { animate: false });
  }, [props.table.table]);

  useEffect(() => {
    const group = layers.current;
    if (group === null) return;
    group.clearLayers();
    if (props.overlay.length > 0) L.polygon(props.overlay, {
      color: "#1F6C9F", weight: 2, fillOpacity: .16, interactive: false,
    }).addTo(group);
    if (props.draft.length > 0) {
      L.polyline(props.draft, { color: "#956400", dashArray: "5 5", interactive: false }).addTo(group);
      props.draft.forEach((point) => L.circleMarker(point, { radius: 4, color: "#956400", interactive: false }).addTo(group));
    }
    // Render hits last so they remain visible when several rows share coordinates.
    [...props.points].sort((a, b) => Number(props.hitIds.has(String(a.id))) - Number(props.hitIds.has(String(b.id))))
      .forEach((point) => {
        const hit = props.hitIds.has(String(point.id));
        const marker = L.circleMarker([point.latitude, point.longitude], {
          radius: hit ? 7 : 5, color: "#fff", weight: 2,
          fillColor: hit ? "#346538" : "#787774", fillOpacity: .95, bubblingMouseEvents: false,
        }).addTo(group);
        const popup = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = String(point.record?.nombre ?? point.record?.name ?? `Registro ${point.id}`);
        popup.append(title);
        const details = document.createElement("p");
        details.textContent = `ID ${point.id} · ${point.latitude.toFixed(6)}, ${point.longitude.toFixed(6)}${hit ? " · Resultado" : ""}`;
        popup.append(details);
        if (point.record) {
          const record = document.createElement("p");
          record.textContent = Object.entries(point.record).map(([key, value]) => `${key}: ${String(value)}`).join(" · ");
          popup.append(record);
        }
        marker.bindPopup(popup);
        const tooltip = document.createElement("span");
        tooltip.textContent = title.textContent;
        marker.bindTooltip(tooltip);
        marker.on("add", () => {
          const element = marker.getElement();
          element?.setAttribute("data-point-id", String(point.id));
          element?.setAttribute("data-match", String(hit));
          element?.setAttribute("tabindex", "0");
          element?.setAttribute("role", "button");
          element?.setAttribute("aria-label", `${title.textContent}, ID ${point.id}${hit ? ", resultado" : ""}`);
          element?.addEventListener("keydown", (event) => {
            if ((event as KeyboardEvent).key === "Enter") { event.stopPropagation(); marker.openPopup(); }
          });
        });
        // The layer is already on the map, so set attributes for its current SVG too.
        marker.fire("add");
      });
    L.circleMarker(props.center, { radius: 8, color: "#9F2F2D", weight: 3,
      fillColor: "#FDEBEC", fillOpacity: .9, interactive: false }).addTo(group);
  }, [props.points, props.hitIds, props.center, props.overlay, props.draft]);

  const fit = () => {
    const coordinates = props.points.map((point): Coordinate => [point.latitude, point.longitude]);
    if (coordinates.length) map.current?.fitBounds(L.latLngBounds(coordinates), { padding: [28, 28], maxZoom: 16, animate: false });
  };

  return <>
    <div className="map-toolbar">
      <button type="button" onClick={() => map.current?.setView(props.table.conventions.origin, 12, { animate: false })}>Restablecer vista</button>
      <button type="button" disabled={props.points.length === 0} onClick={fit}>Ver puntos</button>
      <button type="button" onClick={() => map.current?.panTo(props.center, { animate: false })}>Ver centro</button>
    </div>
    <div ref={host} className="leaflet-map" role="application" aria-label="Mapa OpenStreetMap. Clic o Enter para elegir centro; flechas para mover; más y menos para zoom." />
    {tileError && <p className="warning" role="status">No se pudo cargar parte de la cartografía. Comprueba tu conexión a Internet. Los puntos y las consultas siguen disponibles.
      <button type="button" onClick={() => { setTileError(false); tiles.current?.redraw(); }}>Reintentar cartografía</button></p>}
  </>;
}
