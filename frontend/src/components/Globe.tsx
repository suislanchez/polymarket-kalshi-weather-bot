import { useEffect, useRef, useState, useMemo } from 'react'
import GlobeGL from 'react-globe.gl'
import type { CityWeather } from '../types'

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

  const pointsData = useMemo(() => {
    return cities.map(city => ({
      lat: city.lat,
      lng: city.lon,
      size: 0.15 + city.confidence * 0.2,
      color: city.confidence >= 0.7 ? '#22c55e' : city.confidence >= 0.4 ? '#d97706' : '#dc2626',
      city: city.city.replace('_', ' '),
      confidence: city.confidence,
      high: city.high_temp,
      low: city.low_temp
    }))
  }, [cities])

  const arcsData = useMemo(() => {
    if (cities.length < 2) return []
    const arcs = []
    for (let i = 0; i < Math.min(cities.length - 1, 8); i++) {
      arcs.push({
        startLat: cities[i].lat,
        startLng: cities[i].lon,
        endLat: cities[i + 1].lat,
        endLng: cities[i + 1].lon,
        color: ['rgba(34, 197, 94, 0.4)', 'rgba(34, 197, 94, 0.1)']
      })
    }
    return arcs
  }, [cities])

  const ringsData = useMemo(() => {
    return cities.filter(c => c.confidence >= 0.7).map(city => ({
      lat: city.lat,
      lng: city.lon,
      maxR: 3,
      propagationSpeed: 2,
      repeatPeriod: 1000
    }))
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
        atmosphereAltitude={0.1}
        pointsData={pointsData}
        pointAltitude={0.01}
        pointColor="color"
        pointRadius="size"
        pointsMerge={false}
        arcsData={arcsData}
        arcColor="color"
        arcDashLength={0.4}
        arcDashGap={0.2}
        arcDashAnimateTime={2000}
        arcStroke={0.3}
        ringsData={ringsData}
        ringColor={() => '#22c55e'}
        ringMaxRadius="maxR"
        ringPropagationSpeed="propagationSpeed"
        ringRepeatPeriod="repeatPeriod"
      />

      {/* Overlay stats */}
      <div className="absolute top-3 left-3 bg-black/90 border border-neutral-800 p-3">
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Global Data Feed</div>
        <div className="flex items-center gap-2 mb-1">
          <div className="live-dot" />
          <span className="text-xs text-green-500 mono">{cities.length} markets</span>
        </div>
        <div className="text-[10px] text-neutral-600 mono">
          {pointsData.filter(p => p.color === '#22c55e').length} high confidence
        </div>
      </div>

      {/* Corner decorations */}
      <div className="absolute top-0 left-0 w-8 h-8 border-t border-l border-neutral-800" />
      <div className="absolute top-0 right-0 w-8 h-8 border-t border-r border-neutral-800" />
      <div className="absolute bottom-0 left-0 w-8 h-8 border-b border-l border-neutral-800" />
      <div className="absolute bottom-0 right-0 w-8 h-8 border-b border-r border-neutral-800" />

      {/* Scan line effect */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-30">
        <div className="scan-line" />
      </div>
    </div>
  )
}
