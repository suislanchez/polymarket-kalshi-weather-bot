import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

export class GlobeErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error: unknown) {
    console.error('GlobeView crashed, falling back:', error)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full flex items-center justify-center bg-black">
          <span className="text-[10px] text-neutral-600 uppercase tracking-wider">
            Globe unavailable (WebGL) — see Weather panel below
          </span>
        </div>
      )
    }
    return this.props.children
  }
}
