// @novnc/novnc ships no types; this is the slice of RFB the viewer uses (docs/API.md in the package).
declare module '@novnc/novnc' {
  export default class RFB extends EventTarget {
    constructor(
      target: HTMLElement,
      channel: string | WebSocket,
      options?: { credentials?: { username?: string; password?: string } },
    );

    background: string;
    scaleViewport: boolean;
    resizeSession: boolean;
    viewOnly: boolean;
    disconnect(): void;
    focus(): void;
    /** `down` omitted sends press + release. `code` may be null (no scancode). */
    sendKey(keysym: number, code: string | null, down?: boolean): void;
  }
}
