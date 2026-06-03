import { useState, useEffect } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8765'
const api = axios.create({ baseURL: `${API_BASE}/api` })

interface SettingsData {
  simulation_mode: boolean
  kalshi_configured: boolean
  kalshi_key_id: string
  initial_bankroll: number
  weather_min_edge_threshold: number
  weather_max_trade_size: number
}

interface SettingsModalProps {
  onClose: () => void
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [saveResult, setSaveResult] = useState<{ ok: boolean; message: string } | null>(null)

  // Form state
  const [keyId, setKeyId] = useState('')
  const [privateKeyPem, setPrivateKeyPem] = useState('')
  const [simulationMode, setSimulationMode] = useState(true)
  const [initialBankroll, setInitialBankroll] = useState(10000)
  const [minEdge, setMinEdge] = useState(8)
  const [maxTradeSize, setMaxTradeSize] = useState(100)
  const [kalshiConfigured, setKalshiConfigured] = useState(false)

  useEffect(() => {
    api.get<SettingsData>('/settings')
      .then(({ data }) => {
        setKeyId(data.kalshi_key_id || '')
        setSimulationMode(data.simulation_mode)
        setInitialBankroll(data.initial_bankroll)
        setMinEdge(Math.round(data.weather_min_edge_threshold * 100))
        setMaxTradeSize(data.weather_max_trade_size)
        setKalshiConfigured(data.kalshi_configured)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const { data } = await api.post('/settings/test-connection')
      if (data.ok) {
        const bal = data.balance?.balance
        const balStr = bal != null ? ` — Balance: $${(bal / 100).toFixed(2)}` : ''
        setTestResult({ ok: true, message: `Connected${balStr}` })
      } else {
        setTestResult({ ok: false, message: data.error || 'Connection failed' })
      }
    } catch (e: any) {
      setTestResult({ ok: false, message: e?.response?.data?.detail || 'Request failed' })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveResult(null)
    try {
      const payload: Record<string, any> = {
        simulation_mode: simulationMode,
        initial_bankroll: initialBankroll,
        min_edge: minEdge / 100,
        max_trade_size: maxTradeSize,
      }
      if (keyId.trim()) payload.key_id = keyId.trim()
      if (privateKeyPem.trim()) payload.private_key_pem = privateKeyPem.trim()

      const { data } = await api.post('/settings', payload)
      if (data.ok) {
        setKalshiConfigured(data.kalshi_configured)
        setPrivateKeyPem('') // Clear PEM after save (security)
        setSaveResult({ ok: true, message: 'Settings saved' })
      } else {
        setSaveResult({ ok: false, message: 'Save failed' })
      }
    } catch (e: any) {
      setSaveResult({ ok: false, message: e?.response?.data?.detail || 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-lg bg-black border border-neutral-800 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        style={{ fontFamily: "'Inter', sans-serif" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-white uppercase tracking-widest">Settings</span>
            {kalshiConfigured ? (
              <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-green-500/10 text-green-400 border border-green-500/20">
                Connected
              </span>
            ) : (
              <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Simulation Mode
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-neutral-500 hover:text-neutral-300 text-lg leading-none transition-colors"
          >
            ×
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {loading ? (
            <div className="text-neutral-500 text-xs text-center py-8">Loading…</div>
          ) : (
            <>
              {/* ─── Kalshi API ─── */}
              <section>
                <div className="text-[9px] font-bold uppercase tracking-widest text-neutral-500 mb-3 flex items-center gap-2">
                  <span>Kalshi API</span>
                  <div className="flex-1 h-px bg-neutral-800" />
                </div>

                <div className="space-y-3">
                  {/* Key ID */}
                  <div>
                    <label className="block text-[10px] text-neutral-400 mb-1">
                      API Key ID
                    </label>
                    <input
                      type="text"
                      value={keyId}
                      onChange={e => setKeyId(e.target.value)}
                      placeholder="KALSHI-ACCESS-KEY (uuid format)"
                      className="w-full bg-neutral-950 border border-neutral-800 text-neutral-200 text-[11px] px-2.5 py-2 focus:outline-none focus:border-neutral-600 transition-colors placeholder:text-neutral-700"
                      style={{ fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}
                      spellCheck={false}
                      autoComplete="off"
                    />
                  </div>

                  {/* Private Key PEM */}
                  <div>
                    <label className="block text-[10px] text-neutral-400 mb-1">
                      Private Key (PEM) <span className="text-neutral-600">— paste once, stored securely</span>
                    </label>
                    <textarea
                      value={privateKeyPem}
                      onChange={e => setPrivateKeyPem(e.target.value)}
                      placeholder={`-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----`}
                      rows={5}
                      className="w-full bg-neutral-950 border border-neutral-800 text-neutral-200 text-[10px] px-2.5 py-2 focus:outline-none focus:border-neutral-600 transition-colors placeholder:text-neutral-700 resize-none"
                      style={{ fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}
                      spellCheck={false}
                      autoComplete="off"
                    />
                    {kalshiConfigured && !privateKeyPem && (
                      <p className="text-[9px] text-green-500/70 mt-1">
                        ✓ Private key already configured — leave blank to keep existing
                      </p>
                    )}
                  </div>

                  {/* Test connection */}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleTestConnection}
                      disabled={testing}
                      className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 hover:border-neutral-500 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50"
                    >
                      {testing ? 'Testing…' : 'Test Connection'}
                    </button>

                    {testResult && (
                      <span className={`text-[10px] ${testResult.ok ? 'text-green-400' : 'text-red-400'}`}>
                        {testResult.ok ? '✓' : '✗'} {testResult.message}
                      </span>
                    )}
                  </div>
                </div>
              </section>

              {/* ─── Trading Parameters ─── */}
              <section>
                <div className="text-[9px] font-bold uppercase tracking-widest text-neutral-500 mb-3 flex items-center gap-2">
                  <span>Trading Parameters</span>
                  <div className="flex-1 h-px bg-neutral-800" />
                </div>

                <div className="space-y-3">
                  {/* Min edge */}
                  <div className="flex items-center justify-between gap-4">
                    <label className="text-[10px] text-neutral-400 shrink-0">Min Edge Threshold</label>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        min={1}
                        max={50}
                        step={1}
                        value={minEdge}
                        onChange={e => setMinEdge(Number(e.target.value))}
                        className="w-20 bg-neutral-950 border border-neutral-800 text-neutral-200 text-[11px] px-2 py-1.5 text-right focus:outline-none focus:border-neutral-600 transition-colors"
                        style={{ fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}
                      />
                      <span className="text-[10px] text-neutral-500">%</span>
                    </div>
                  </div>

                  {/* Max trade size */}
                  <div className="flex items-center justify-between gap-4">
                    <label className="text-[10px] text-neutral-400 shrink-0">Max Trade Size</label>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-neutral-500">$</span>
                      <input
                        type="number"
                        min={1}
                        step={10}
                        value={maxTradeSize}
                        onChange={e => setMaxTradeSize(Number(e.target.value))}
                        className="w-24 bg-neutral-950 border border-neutral-800 text-neutral-200 text-[11px] px-2 py-1.5 text-right focus:outline-none focus:border-neutral-600 transition-colors"
                        style={{ fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}
                      />
                    </div>
                  </div>

                  {/* Initial bankroll */}
                  <div className="flex items-center justify-between gap-4">
                    <label className="text-[10px] text-neutral-400 shrink-0">Initial Bankroll</label>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-neutral-500">$</span>
                      <input
                        type="number"
                        min={100}
                        step={100}
                        value={initialBankroll}
                        onChange={e => setInitialBankroll(Number(e.target.value))}
                        className="w-28 bg-neutral-950 border border-neutral-800 text-neutral-200 text-[11px] px-2 py-1.5 text-right focus:outline-none focus:border-neutral-600 transition-colors"
                        style={{ fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}
                      />
                    </div>
                  </div>

                  {/* Simulation mode toggle */}
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <label className="text-[10px] text-neutral-400">Simulation Mode</label>
                      <p className="text-[9px] text-neutral-600 mt-0.5">
                        {simulationMode ? 'No real orders placed' : 'Live mode — paper trading (no real Kalshi fills)'}
                      </p>
                    </div>
                    <button
                      onClick={() => setSimulationMode(v => !v)}
                      className={`relative w-10 h-5 rounded-none transition-colors border ${
                        simulationMode
                          ? 'bg-amber-500/20 border-amber-500/40'
                          : 'bg-green-500/20 border-green-500/40'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 w-4 h-4 transition-all ${
                          simulationMode
                            ? 'left-0.5 bg-amber-400'
                            : 'left-[calc(100%-1.125rem)] bg-green-400'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </section>

              {saveResult && (
                <p className={`text-[10px] ${saveResult.ok ? 'text-green-400' : 'text-red-400'}`}>
                  {saveResult.ok ? '✓' : '✗'} {saveResult.message}
                </p>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-neutral-800 shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-neutral-400 hover:text-neutral-200 text-[10px] uppercase tracking-wider transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="px-4 py-1.5 bg-neutral-800 hover:bg-neutral-700 border border-neutral-600 text-white text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
