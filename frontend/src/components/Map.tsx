import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import type { CityWeather } from '../types'
import 'leaflet/dist/leaflet.css'

interface Props {
  cities: CityWeather[]
}

function MapController({ cities }: { cities: CityWeather[] }) {
  const map = useMap()

  useEffect(() => {
    if (cities.length > 0) {
      const bounds = cities.map(c => [c.lat, c.lon] as [number, number])
      map.fitBounds(bounds, { padding: [20, 20] })
    }
  }, [cities, map])

  return null
}

export function Map({ cities }: Props) {
  const [selectedCity, setSelectedCity] = useState<CityWeather | null>(null)

  const getMarkerColor = (confidence: number): string => {
    if (confidence >= 0.7) return '#22c55e'
    if (confidence >= 0.4) return '#d97706'
    return '#dc2626'
  }

  const getMarkerRadius = (confidence: number): number => {
    return 6 + confidence * 4
  }

  return (
    <div className="h-[350px] relative">
      <MapContainer
        center={[39.8283, -98.5795]}
        zoom={4}
        style={{ height: '100%', width: '100%', background: '#0a0a0a' }}
        zoomControl={true}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
        />
        <MapController cities={cities} />

        {cities.map((city) => (
          <CircleMarker
            key={city.city}
            center={[city.lat, city.lon]}
            radius={getMarkerRadius(city.confidence)}
            pathOptions={{
              color: getMarkerColor(city.confidence),
              fillColor: getMarkerColor(city.confidence),
              fillOpacity: 0.6,
              weight: 1,
            }}
            eventHandlers={{
              click: () => setSelectedCity(city),
            }}
          >
            <Popup>
              <div className="p-3 min-w-[200px]">
                <div className="text-xs text-neutral-500 uppercase tracking-wider mb-1">Weather Market</div>
                <div className="text-sm font-semibold text-neutral-100 capitalize mb-3">
                  {city.city.replace('_', ' ')}
                </div>

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <div className="text-[10px] text-neutral-600 uppercase">High</div>
                    <div className="text-lg font-semibold text-green-500 tabular-nums">
                      {city.high_temp.toFixed(0)}°F
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-neutral-600 uppercase">Low</div>
                    <div className="text-lg font-semibold text-blue-500 tabular-nums">
                      {city.low_temp.toFixed(0)}°F
                    </div>
                  </div>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Ensemble</span>
                    <span className="text-neutral-300 tabular-nums">{city.ensemble_count} models</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">Confidence</span>
                    <span className="tabular-nums" style={{ color: getMarkerColor(city.confidence) }}>
                      {(city.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">P(&gt;50°F)</span>
                    <span className="text-neutral-300 tabular-nums">{(city.prob_above_50 * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-500">P(&gt;60°F)</span>
                    <span className="text-neutral-300 tabular-nums">{(city.prob_above_60 * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-black/90 border border-neutral-800 p-3 z-[1000]">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Confidence</div>
        <div className="space-y-1.5 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-neutral-400">High (70%+)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-neutral-400">Medium</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-neutral-400">Low</span>
          </div>
        </div>
      </div>
    </div>
  )
}
