import { useRef, useEffect, useMemo, useState } from 'react'
import GlobeGL from 'react-globe.gl'
import type { CityWeather } from '../types'

interface Props {
  cities: CityWeather[]
  onCitySelect?: (city: CityWeather | null) => void
}

export function Globe({ cities, onCitySelect }: Props) {
  const globeRef = useRef<any>(null)
  const [selectedCity, setSelectedCity] = useState<CityWeather | null>(null)

  // Format city data for globe
  const pointsData = useMemo(() => {
    return cities.map(city => ({
      lat: city.lat,
      lng: city.lon,
      city: city.city,
      temp: city.high_temp,
      confidence: city.confidence,
      color: city.confidence >= 0.7 ? '#00ff88' : city.confidence >= 0.4 ? '#ffaa00' : '#ff4466',
      size: 0.5 + (city.confidence * 0.5),
      data: city
    }))
  }, [cities])

  // Auto-rotate globe
  useEffect(() => {
    if (globeRef.current) {
      globeRef.current.controls().autoRotate = true
      globeRef.current.controls().autoRotateSpeed = 0.5
      globeRef.current.pointOfView({ lat: 30, lng: -40, altitude: 2.5 }, 1000)
    }
  }, [])

  // Stop rotation on hover
  const handlePointHover = (point: any) => {
    if (globeRef.current) {
      globeRef.current.controls().autoRotate = !point
    }
  }

  const handlePointClick = (point: any) => {
    if (point) {
      setSelectedCity(point.data)
      onCitySelect?.(point.data)
      // Zoom to city
      if (globeRef.current) {
        globeRef.current.pointOfView({ lat: point.lat, lng: point.lng, altitude: 1.5 }, 1000)
      }
    }
  }

  return (
    <div className="relative w-full h-[400px] rounded-xl overflow-hidden">
      <GlobeGL
        ref={globeRef}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
        backgroundImageUrl="//unpkg.com/three-globe/example/img/night-sky.png"
        pointsData={pointsData}
        pointLat="lat"
        pointLng="lng"
        pointColor="color"
        pointAltitude={0.01}
        pointRadius="size"
        pointLabel={(d: any) => `
          <div class="glass-card p-3 text-sm">
            <div class="font-bold capitalize mb-1">${d.city.replace('_', ' ')}</div>
            <div class="text-gray-300">High: ${d.temp.toFixed(0)}°F</div>
            <div class="text-gray-300">Confidence: ${(d.confidence * 100).toFixed(0)}%</div>
          </div>
        `}
        onPointHover={handlePointHover}
        onPointClick={handlePointClick}
        atmosphereColor="#4488ff"
        atmosphereAltitude={0.15}
        width={undefined}
        height={400}
      />

      {/* City info overlay */}
      {selectedCity && (
        <div className="absolute bottom-4 left-4 glass-card p-4 max-w-xs animate-in fade-in slide-in-from-bottom-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-lg capitalize">
              {selectedCity.city.replace('_', ' ')}
            </h3>
            <button
              onClick={() => {
                setSelectedCity(null)
                onCitySelect?.(null)
                if (globeRef.current) {
                  globeRef.current.pointOfView({ lat: 30, lng: -40, altitude: 2.5 }, 1000)
                  globeRef.current.controls().autoRotate = true
                }
              }}
              className="text-gray-400 hover:text-white"
            >
              ×
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-400 block">High</span>
              <span className="text-xl font-bold text-emerald-400">
                {selectedCity.high_temp.toFixed(0)}°F
              </span>
            </div>
            <div>
              <span className="text-gray-400 block">Low</span>
              <span className="text-xl font-bold text-blue-400">
                {selectedCity.low_temp.toFixed(0)}°F
              </span>
            </div>
            <div>
              <span className="text-gray-400 block">Ensemble</span>
              <span className="font-medium">{selectedCity.ensemble_count} members</span>
            </div>
            <div>
              <span className="text-gray-400 block">Confidence</span>
              <span className="font-medium">{(selectedCity.confidence * 100).toFixed(0)}%</span>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-gray-700">
            <div className="text-xs text-gray-400 mb-2">Probabilities</div>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span>Above 50°F</span>
                <span className={selectedCity.prob_above_50 > 0.5 ? 'text-emerald-400' : 'text-gray-400'}>
                  {(selectedCity.prob_above_50 * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span>Above 60°F</span>
                <span className={selectedCity.prob_above_60 > 0.5 ? 'text-emerald-400' : 'text-gray-400'}>
                  {(selectedCity.prob_above_60 * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="absolute top-4 right-4 glass-card p-3 text-xs">
        <div className="text-gray-400 mb-2">Confidence</div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-emerald-400" />
            <span>High (70%+)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-amber-400" />
            <span>Medium (40-70%)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <span>Low (&lt;40%)</span>
          </div>
        </div>
      </div>
    </div>
  )
}
