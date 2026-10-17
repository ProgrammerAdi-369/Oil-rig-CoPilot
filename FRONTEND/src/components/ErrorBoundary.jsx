import { Component } from "react";

// One message that fails to render must not blank the whole app.
export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? (
      <div className='error-note'>
        <strong>This message could not be displayed.</strong>
        <p>The answer is saved; reload the page to see it again.</p>
      </div>
    ) : (
      this.props.children
    );
  }
}
