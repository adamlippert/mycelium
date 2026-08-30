import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

describe('the test harness', () => {
  it('renders a component and finds it in the document', () => {
    render(<p>mycelium</p>);
    expect(screen.getByText('mycelium')).toBeInTheDocument();
  });
});
