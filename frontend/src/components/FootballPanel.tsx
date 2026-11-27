import React, { useState } from 'react';
import { FootballFixture } from '../types';

interface FootballPanelProps {
  fixtures: FootballFixture[];
  loading: boolean;
}

const StatusBadge = ({ status }: { status: 'good' | 'bad' | 'neutral' }) => {
  const color = status === 'good' ? 'text-green-400' : status === 'bad' ? 'text-red-400' : 'text-gray-400';
  return <span className={`text-xs font-bold uppercase ${color}`}>{status}</span>;
};

const BttsDot = ({ btts }: { btts: boolean }) => (
  <div className={`w-2 h-2 rounded-full ${btts ? 'bg-green-500' : 'bg-red-500'}`} />
);

const FormMatchDetail = ({ match }: { match: FootballFixture['home_form'][0] }) => (
  <div className="flex items-center gap-2 text-xs text-gray-300 py-1 border-b border-gray-700 last:border-0">
    <span className="w-20">{new Date(match.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
    <span className="flex-1 text-right">{match.opponent}</span>
    <span className="font-mono w-14 text-center">{match.score}</span>
    <span className={match.both_scored ? 'text-green-400' : 'text-red-400'}>{match.both_scored ? '✓ BTTS' : '✗'}</span>
  </div>
);

const H2HMatchDetail = ({ match }: { match: FootballFixture['h2h_meetings'][0] }) => (
  <div className="flex items-center gap-2 text-xs text-gray-300 py-1 border-b border-gray-700 last:border-0">
    <span className="w-20">{new Date(match.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
    <span className="flex-1 text-center font-mono">{match.home} {match.score} {match.away}</span>
  </div>
);

export const FootballPanel: React.FC<FootballPanelProps> = ({ fixtures, loading }) => {
  if (loading) {
    return <div className="p-4 text-gray-400">Loading EPL fixtures...</div>;
  }

  if (fixtures.length === 0) {
    return <div className="p-4 text-gray-400">No EPL fixtures in next 7 days.</div>;
  }

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="space-y-4 p-2">
      {fixtures.map((f) => {
        const isExpanded = expandedId === f.id;

        return (
          <div key={f.id} className="bg-gray-800 p-3 rounded-lg border border-gray-700 text-sm">
            <div
              className="flex justify-between items-center mb-2 cursor-pointer hover:bg-gray-700 rounded p-1"
              onClick={() => toggleExpand(f.id)}
            >
              <span className="font-bold text-gray-100">
                ⚽ {f.home_team} vs {f.away_team}
              </span>
              <div className="space-x-2">
                <StatusBadge status={f.home_form_status as any} />
                <StatusBadge status={f.away_form_status as any} />
                <span className="text-gray-400 text-xs">{isExpanded ? '▲' : '▼'}</span>
              </div>
            </div>

            <div className="text-gray-400 text-xs mb-2">
              {new Date(f.date).toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
              })} ET · Avg GF: {f.home_avg_gf.toFixed(1)} / {f.away_avg_gf.toFixed(1)} · H2H Avg: {f.h2h_total_avg.toFixed(1)}
            </div>

            <div className="flex justify-between text-xs mb-2">
              <div>
                <div className="text-gray-500 mb-1">Form (Home)</div>
                <div className="flex gap-1">
                  {f.home_form.slice(0, 5).map((m, i) => <BttsDot key={i} btts={m.both_scored} />)}
                </div>
              </div>
              <div>
                <div className="text-gray-500 mb-1">Form (Away)</div>
                <div className="flex gap-1">
                  {f.away_form.slice(0, 5).map((m, i) => <BttsDot key={i} btts={m.both_scored} />)}
                </div>
              </div>
            </div>

            {f.kalshi && (
              <div className={`mt-2 p-2 rounded ${f.bet_signal ? 'bg-amber-900 border border-amber-600' : 'bg-gray-700'}`}>
                <div className="flex justify-between items-center">
                  <span className="text-gray-200">Over 1.5 Goals</span>
                  <span className="font-bold text-gray-100">{(f.kalshi.over_price * 100).toFixed(0)}¢</span>
                </div>
                {f.bet_signal && (
                  <div className="mt-1 text-center font-bold text-amber-200 uppercase text-xs">
                    [BET!]
                  </div>
                )}
              </div>
            )}

            {isExpanded && (
              <div className="mt-3 pt-3 border-t border-gray-700 space-y-3">
                {/* Home Form Details */}
                <div>
                  <div className="text-gray-500 text-xs mb-1">{f.home_team} Last 5</div>
                  <div className="bg-gray-900 rounded p-2">
                    {f.home_form.map((m) => <FormMatchDetail key={m.date + m.opponent} match={m} />)}
                  </div>
                </div>

                {/* Away Form Details */}
                <div>
                  <div className="text-gray-500 text-xs mb-1">{f.away_team} Last 5</div>
                  <div className="bg-gray-900 rounded p-2">
                    {f.away_form.map((m) => <FormMatchDetail key={m.date + m.opponent} match={m} />)}
                  </div>
                </div>

                {/* H2H Details */}
                {f.h2h_meetings.length > 0 && (
                  <div>
                    <div className="text-gray-500 text-xs mb-1">Head-to-Head ({f.h2h_count} meetings)</div>
                    <div className="bg-gray-900 rounded p-2">
                      {f.h2h_meetings.map((m) => <H2HMatchDetail key={m.date + m.home + m.away} match={m} />)}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
