/**
 * Swipe comparison curtain utility (Section 7.10, 9.1).
 *
 * Enables smooth horizontal split-screen swipe comparison between:
 *  - AI-generated parcels / footprints (left side)
 *  - Existing reference cadastral GIS layer or raw drone orthophoto (right side)
 */

export interface SwipeOptions {
  container: HTMLElement;
  initialPosition?: number; // 0 to 100 percent
  onPositionChange?: (percent: number) => void;
}

export class SwipeCompareController {
  private container: HTMLElement;
  private slider: HTMLDivElement | null = null;
  private isDragging = false;
  private position = 50; // percentage
  private onPositionChange?: (percent: number) => void;

  constructor(options: SwipeOptions) {
    this.container = options.container;
    this.position = options.initialPosition ?? 50;
    this.onPositionChange = options.onPositionChange;
    this.initSlider();
  }

  private initSlider(): void {
    const slider = document.createElement('div');
    slider.className =
      'absolute top-0 bottom-0 z-30 flex items-center justify-center cursor-ew-resize select-none pointer-events-auto';
    slider.style.left = `${this.position}%`;
    slider.style.transform = 'translateX(-50%)';

    slider.innerHTML = `
      <div class="w-0.5 h-full bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]"></div>
      <div class="absolute w-8 h-8 rounded-full bg-slate-900 border-2 border-cyan-400 flex items-center justify-center shadow-lg text-cyan-400 hover:scale-110 transition-transform">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
        </svg>
      </div>
    `;

    const startDrag = (e: MouseEvent | TouchEvent) => {
      this.isDragging = true;
      e.preventDefault();
    };

    const onMove = (e: MouseEvent | TouchEvent) => {
      if (!this.isDragging) return;
      const rect = this.container.getBoundingClientRect();
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const offset = clientX - rect.left;
      const pct = Math.max(0, Math.min(100, (offset / rect.width) * 100));
      this.setPosition(pct);
    };

    const stopDrag = () => {
      this.isDragging = false;
    };

    slider.addEventListener('mousedown', startDrag);
    slider.addEventListener('touchstart', startDrag, { passive: false });
    window.addEventListener('mousemove', onMove);
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('mouseup', stopDrag);
    window.addEventListener('touchend', stopDrag);

    this.container.appendChild(slider);
    this.slider = slider;
  }

  setPosition(percent: number): void {
    this.position = percent;
    if (this.slider) {
      this.slider.style.left = `${percent}%`;
    }
    this.onPositionChange?.(percent);
  }

  getPosition(): number {
    return this.position;
  }

  destroy(): void {
    if (this.slider && this.slider.parentElement) {
      this.slider.parentElement.removeChild(this.slider);
    }
    this.slider = null;
  }
}
