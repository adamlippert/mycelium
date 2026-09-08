import { describe, it, expect, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useFocusTrap } from './useFocusTrap';

function buildPanel() {
  const outside = document.createElement('button');
  outside.textContent = 'outside';
  document.body.appendChild(outside);

  const container = document.createElement('div');
  const first = document.createElement('button');
  first.textContent = 'first';
  const last = document.createElement('button');
  last.textContent = 'last';
  container.appendChild(first);
  container.appendChild(last);
  document.body.appendChild(container);

  return { outside, container, first, last };
}

function pressTab(shiftKey = false) {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true }));
}

describe('useFocusTrap', () => {
  let cleanup: (() => void) | undefined;

  afterEach(() => {
    cleanup?.();
    cleanup = undefined;
    document.body.innerHTML = '';
  });

  it('pulls focus back into the panel when Tab is pressed while focus is outside it', () => {
    const { outside, container } = buildPanel();
    const ref = { current: container };
    const { unmount } = renderHook(() => useFocusTrap(ref));
    cleanup = unmount;

    outside.focus();
    expect(document.activeElement).toBe(outside);

    pressTab();

    expect(container.contains(document.activeElement)).toBe(true);
  });

  it('removes the document keydown listener on unmount', () => {
    const { outside, container } = buildPanel();
    const ref = { current: container };
    const { unmount } = renderHook(() => useFocusTrap(ref));
    unmount();

    outside.focus();
    pressTab();

    expect(document.activeElement).toBe(outside);
  });
});
