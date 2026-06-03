import { useEffect, useRef, useMemo, useCallback } from 'react'
import Globe from 'react-globe.gl'
import type { WeatherForecast, WeatherSignal } from '../types'

interface Props {
  forecasts: WeatherForecast[]
  signals: WeatherSignal[]
}

interface CityMarker {
  lat: number
  lng: number
  name: string
  key: string
  forecast: WeatherForecast | null
  bestSignal: WeatherSignal | null
  hasActionable: boolean
}

const CITIES: Record<string, { lat: number; lng: number; name: string }> = {
  nyc: { lat: 40.7128, lng: -74.006, name: 'NYC' },
  chicago: { lat: 41.8781, lng: -87.6298, name: 'CHI' },
  miami: { lat: 25.7617, lng: -80.1918, name: 'MIA' },
  los_angeles: { lat: 34.0522, lng: -118.2437, name: 'LA' },
  denver: { lat: 39.7392, lng: -104.9903, name: 'DEN' },
}

export function GlobeView({ forecasts, signals }: Props) {
  const globeRef = useRef<any>(null)

  const markers: CityMarker[] = useMemo(() => {
    return Object.entries(CITIES).map(([key, city]) => {
      const forecast = forecasts.find(f => f.city_key === key) || null
      const citySignals = signals.filter(s => s.city_key === key)
      const actionableSignals = citySignals.filter(s => s.actionable)
      const bestSignal = actionableSignals.length > 0
        ? actionableSignals.reduce((a, b) => Math.abs(a.edge) > Math.abs(b.edge) ? a : b)
        : citySignals.length > 0
          ? citySignals.reduce((a, b) => Math.abs(a.edge) > Math.abs(b.edge) ? a : b)
          : null

      return {
        lat: city.lat,
        lng: city.lng,
        name: city.name,
        key,
        forecast,
        bestSignal,
        hasActionable: actionableSignals.length > 0,
      }
    })
  }, [forecasts, signals])

  useEffect(() => {
    if (globeRef.current) {
      globeRef.current.pointOfView({ lat: 39.5, lng: -98.35, altitude: 2.2 }, 1000)
      const controls = globeRef.current.controls()
      controls.autoRotate = true
      controls.autoRotateSpeed = 0.3
      controls.enableZoom = true
      controls.enableRotate = true
      controls.enablePan = false
    }
  }, [])

  const handleInteraction = useCallback(() => {
    if (globeRef.current) {
      globeRef.current.controls().autoRotate = false
      setTimeout(() => {
        if (globeRef.current) {
          globeRef.current.controls().autoRotate = true
        }
      }, 5000)
    }
  }, [])

  const markerElement = useCallback((d: object) => {
    const marker = d as CityMarker
    const el = document.createElement('div')
    el.className = 'city-marker'

    const dotColor = marker.hasActionable ? '#22c55e' : marker.bestSignal ? '#d97706' : '#525252'

    const dot = document.createElement('div')
    dot.className = 'marker-dot'
    dot.style.backgroundColor = dotColor
    dot.style.color = dotColor
    el.appendChild(dot)

    const label = document.createElement('div')
    label.className = 'marker-label'

    const nameSpan = document.createElement('div')
    nameSpan.className = 'marker-name'
    nameSpan.textContent = marker.name
    label.appendChild(nameSpan)

    if (marker.forecast) {
      const tempSpan = document.createElement('div')
      tempSpan.className = 'marker-temp'
      tempSpan.style.color = '#e5e5e5'
      tempSpan.textContent = `${marker.forecast.mean_high.toFixed(0)}F`
      label.appendChild(tempSpan)
    }

    if (marker.bestSignal) {
      const edgeSpan = document.createElement('div')
      edgeSpan.className = 'marker-edge'
      const edgeVal = (marker.bestSignal.edge * 100).toFixed(1)
      edgeSpan.style.color = marker.bestSignal.edge > 0 ? '#22c55e' : '#dc2626'
      edgeSpan.textContent = `${marker.bestSignal.edge > 0 ? '+' : ''}${edgeVal}%`
      label.appendChild(edgeSpan)
    }

    el.appendChild(label)
    return el
  }, [])

  const containerRef = useRef<HTMLDivElement>(null)

  return (
    <div ref={containerRef} className="globe-container w-full h-full flex items-center justify-center overflow-hidden">
      <Globe
        ref={globeRef}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        backgroundColor="rgba(0,0,0,0)"
        atmosphereColor="#1a1a2e"
        atmosphereAltitude={0.15}
        htmlElementsData={markers}
        htmlElement={markerElement}
        htmlAltitude={0.01}
        onGlobeClick={handleInteraction}
        onGlobeRightClick={handleInteraction}
      />
    </div>
  )
}
