import { useState, useCallback } from 'react'
import MapGL, { Marker, Popup } from 'react-map-gl'
import { MapPin } from 'lucide-react'
import type { CityWeather } from '../types'
import 'mapbox-gl/dist/mapbox-gl.css'

// Free public token for demo - replace with your own for production
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || 'pk.eyJ1IjoibWFwYm94IiwiYSI6ImNpejY4M29iazA2Z2gycXA4N2pmbDZmangifQ.-g_vE53SD2WrJ6tFX7QHmA'

interface Props {
  cities: CityWeather[]
}

export function Map({ cities }: Props) {
  const [selectedCity, setSelectedCity] = useState<CityWeather | null>(null)
  const [viewState, setViewState] = useState({
    longitude: -98.5795,
    latitude: 39.8283,
    zoom: 3
  })

  const getMarkerColor = (confidence: number) => {
    if (confidence >= 0.7) return 'text-emerald-400'
    if (confidence >= 0.4) return 'text-yellow-400'
    return 'text-red-400'
  }

  return (
    <div className="h-80 rounded-lg overflow-hidden">
      <MapGL
        {...viewState}
        onMove={evt => setViewState(evt.viewState)}
        mapStyle="mapbox://styles/mapbox/dark-v11"
        mapboxAccessToken={MAPBOX_TOKEN}
        style={{ width: '100%', height: '100%' }}
      >
        {cities.map((city) => (
          <Marker
            key={city.city}
            longitude={city.lon}
            latitude={city.lat}
            anchor="bottom"
            onClick={(e) => {
              e.originalEvent.stopPropagation()
              setSelectedCity(city)
            }}
          >
            <div className={`cursor-pointer transition-transform hover:scale-125 ${getMarkerColor(city.confidence)}`}>
              <MapPin className="w-6 h-6" fill="currentColor" />
            </div>
          </Marker>
        ))}

        {selectedCity && (
          <Popup
            longitude={selectedCity.lon}
            latitude={selectedCity.lat}
            anchor="top"
            onClose={() => setSelectedCity(null)}
            closeButton={true}
            closeOnClick={false}
            className="text-gray-900"
          >
            <div className="p-2 min-w-48">
              <h3 className="font-bold capitalize mb-2">{selectedCity.city.replace('_', ' ')}</h3>

              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span>High:</span>
                  <span className="font-medium">{selectedCity.high_temp.toFixed(0)}°F</span>
                </div>
                <div className="flex justify-between">
                  <span>Low:</span>
                  <span className="font-medium">{selectedCity.low_temp.toFixed(0)}°F</span>
                </div>
                <div className="flex justify-between">
                  <span>Ensemble:</span>
                  <span className="font-medium">{selectedCity.ensemble_count} members</span>
                </div>
                <div className="flex justify-between">
                  <span>Confidence:</span>
                  <span className="font-medium">{(selectedCity.confidence * 100).toFixed(0)}%</span>
                </div>

                <hr className="my-2" />

                <div className="text-xs text-gray-600">
                  <div>P(above 40°F): {(selectedCity.prob_above_40 * 100).toFixed(0)}%</div>
                  <div>P(above 50°F): {(selectedCity.prob_above_50 * 100).toFixed(0)}%</div>
                  <div>P(above 60°F): {(selectedCity.prob_above_60 * 100).toFixed(0)}%</div>
                </div>
              </div>
            </div>
          </Popup>
        )}
      </MapGL>
    </div>
  )
}
