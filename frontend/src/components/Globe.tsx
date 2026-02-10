import { useEffect, useRef, useState, useMemo } from 'react'
import GlobeGL from 'react-globe.gl'
import type { CityWeather } from '../types'
import { tempToColor, getConfidenceColor } from '../utils'

interface Props {
  cities: CityWeather[]
}

export function Globe({ cities }: Props) {
  const globeEl = useRef<any>(null)
  const [dimensions, setDimensions] = useState({ width: 400, height: 350 })
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (containerRef.current) {
      const updateDimensions = () => {
        if (containerRef.current) {
          setDimensions({
            width: containerRef.current.offsetWidth,
            height: containerRef.current.offsetHeight
          })
        }
      }
      updateDimensions()
      window.addEventListener('resize', updateDimensions)
      return () => window.removeEventListener('resize', updateDimensions)
    }
  }, [])

  useEffect(() => {
    if (globeEl.current) {
      globeEl.current.controls().autoRotate = true
      globeEl.current.controls().autoRotateSpeed = 0.3
      globeEl.current.pointOfView({ lat: 39.8, lng: -98.5, altitude: 2.2 })
    }
  }, [])

  // City points with temperature-based coloring
  const pointsData = useMemo(() => {
    return cities.map(city => ({
      lat: city.lat,
      lng: city.lon,
      size: 0.12 + city.confidence * 0.15,
      color: tempToColor(city.high_temp),
      city: city.city.replace('_', ' '),
      confidence: city.confidence,
      high: city.high_temp,
      low: city.low_temp
    }))
  }, [cities])

  // Connection arcs between cities
  const arcsData = useMemo(() => {
    if (cities.length < 2) return []
    const arcs = []
    for (let i = 0; i < Math.min(cities.length - 1, 8); i++) {
      const avgConfidence = (cities[i].confidence + cities[i + 1].confidence) / 2
      const arcColor = getConfidenceColor(avgConfidence)
      arcs.push({
        startLat: cities[i].lat,
        startLng: cities[i].lon,
        endLat: cities[i + 1].lat,
        endLng: cities[i + 1].lon,
        color: [`${arcColor}66`, `${arcColor}22`]
      })
    }
    return arcs
  }, [cities])

  // Confidence-based pulsing rings
  const ringsData = useMemo(() => {
    return cities.map(city => ({
      lat: city.lat,
      lng: city.lon,
      maxR: city.confidence >= 0.7 ? 4 : city.confidence >= 0.4 ? 2.5 : 1.5,
      propagationSpeed: city.confidence >= 0.7 ? 3 : city.confidence >= 0.4 ? 2 : 1,
      repeatPeriod: city.confidence >= 0.7 ? 800 : city.confidence >= 0.4 ? 1200 : 2000,
      color: getConfidenceColor(city.confidence)
    }))
  }, [cities])

  // HTML markers for city labels
  const labelsData = useMemo(() => {
    return cities.filter(c => c.confidence >= 0.5).map(city => ({
      lat: city.lat,
      lng: city.lon,
      city: city.city.replace('_', ' '),
      temp: city.high_temp,
      confidence: city.confidence,
      color: getConfidenceColor(city.confidence)
    }))
  }, [cities])

  // Calculate temperature stats
  const tempStats = useMemo(() => {
    if (cities.length === 0) return { min: 0, max: 0, avg: 0 }
    const temps = cities.map(c => c.high_temp)
    return {
      min: Math.round(Math.min(...temps)),
      max: Math.round(Math.max(...temps)),
      avg: Math.round(temps.reduce((a, b) => a + b, 0) / temps.length)
    }
  }, [cities])

  return (
    <div ref={containerRef} className="h-[350px] relative globe-container bg-black overflow-hidden">
      <GlobeGL
        ref={globeEl}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
        atmosphereColor="#22c55e"
        atmosphereAltitude={0.12}
        pointsData={pointsData}
        pointAltitude={0.02}
        pointColor="color"
        pointRadius="size"
        pointsMerge={false}
        arcsData={arcsData}
        arcColor="color"
        arcDashLength={0.5}
        arcDashGap={0.2}
        arcDashAnimateTime={1500}
        arcStroke={0.4}
        ringsData={ringsData}
        ringColor="color"
        ringMaxRadius="maxR"
        ringPropagationSpeed="propagationSpeed"
        ringRepeatPeriod="repeatPeriod"
        htmlElementsData={labelsData}
        htmlElement={(d: any) => {
          const el = document.createElement('div')
          el.className = 'city-marker'
          el.innerHTML = `
            <div class="marker-dot" style="background: ${d.color}; box-shadow: 0 0 8px ${d.color}"></div>
            <div class="marker-label">
              <span class="marker-name">${d.city}</span>
              <span class="marker-temp" style="color: ${d.color}">${Math.round(d.temp)}°F</span>
            </div>
          `
          return el
        }}
      />

      {/* Temperature legend */}
      <div className="absolute bottom-3 left-3 bg-black/90 border border-neutral-800 p-2">
        <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1.5">Temp Range</div>
        <div className="flex items-center gap-1.5">
          <div className="w-16 h-1.5 bg-gradient-to-r from-blue-500 via-yellow-500 via-orange-500 to-red-500 rounded-full" />
          <div className="flex justify-between text-[9px] text-neutral-600 w-full">
            <span>{tempStats.min}°</span>
            <span>{tempStats.max}°</span>
          </div>
        </div>
      </div>

      {/* Overlay stats */}
      <div className="absolute top-3 left-3 bg-black/90 border border-neutral-800 p-3">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Global Data Feed</div>
        <div className="flex items-center gap-2 mb-1">
          <div className="live-dot" />
          <span className="text-xs text-green-500 mono">{cities.length} cities</span>
        </div>
        <div className="text-[10px] text-neutral-600 mono">
          Avg: {tempStats.avg}°F
        </div>
        <div className="text-[10px] text-neutral-600 mono">
          {pointsData.filter(p => cities.find(c => c.city.replace('_', ' ') === p.city)?.confidence! >= 0.7).length} high confidence
        </div>
      </div>

      {/* Confidence legend */}
      <div className="absolute top-3 right-3 bg-black/90 border border-neutral-800 p-2">
        <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1.5">Confidence</div>
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-[9px] text-neutral-600">High (&gt;70%)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-[9px] text-neutral-600">Medium</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-[9px] text-neutral-600">Low</span>
          </div>
        </div>
      </div>

      {/* Corner decorations */}
      <div className="absolute top-0 left-0 w-8 h-8 border-t border-l border-neutral-800" />
      <div className="absolute top-0 right-0 w-8 h-8 border-t border-r border-neutral-800" />
      <div className="absolute bottom-0 left-0 w-8 h-8 border-b border-l border-neutral-800" />
      <div className="absolute bottom-0 right-0 w-8 h-8 border-b border-r border-neutral-800" />

      {/* Scan line effect */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-20">
        <div className="scan-line" />
      </div>
    </div>
  )
}
