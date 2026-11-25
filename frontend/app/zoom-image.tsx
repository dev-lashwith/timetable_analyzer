"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent, ReactNode } from "react";

const ZOOM = 2.4;
const MODAL_START_ZOOM = 2.2;

type Geometry = {
  left: number;
  top: number;
  width: number;
  height: number;
  naturalWidth: number;
  naturalHeight: number;
};

type ZoomImageProps = {
  src: string;
  alt: string;
  className?: string;
  children?: ReactNode;
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/**
 * Hover-to-zoom inside the image frame itself, like Amazon / Flipkart.
 * The visible pixels are magnified around the cursor; clicking opens a
 * full-screen cursor-following zoom.
 */
export default function ZoomImage({ src, alt, className = "", children }: ZoomImageProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [hovering, setHovering] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [cursor, setCursor] = useState({ x: 0, y: 0 });
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [modalPoint, setModalPoint] = useState({ x: 0.5, y: 0.5 });
  const [modalZoom, setModalZoom] = useState(MODAL_START_ZOOM);
  const [stageSize, setStageSize] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    setHovering(false);
    setExpanded(false);
    setGeometry(null);
  }, [src]);

  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    const measureStage = () => {
      const stage = stageRef.current;
      if (stage) setStageSize({ width: stage.clientWidth, height: stage.clientHeight });
    };
    measureStage();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", measureStage);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", measureStage);
    };
  }, [expanded]);

  /** Rectangle of the real pixels inside the <img>, relative to the frame. */
  function readGeometry(): Geometry | null {
    const frame = frameRef.current;
    const image = frame?.querySelector("img");
    if (!frame || !image || !image.naturalWidth || !image.naturalHeight) return null;

    const frameRect = frame.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    if (!imageRect.width || !imageRect.height) return null;

    const fit = Math.min(imageRect.width / image.naturalWidth, imageRect.height / image.naturalHeight);
    const width = image.naturalWidth * fit;
    const height = image.naturalHeight * fit;

    return {
      left: imageRect.left - frameRect.left + (imageRect.width - width) / 2,
      top: imageRect.top - frameRect.top + (imageRect.height - height) / 2,
      width,
      height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    };
  }

  function updatePointer(event: MouseEvent<HTMLDivElement>) {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return;
    setCursor({ x: event.clientX - rect.left, y: event.clientY - rect.top });
    setGeometry(readGeometry());
  }

  const active = hovering && !expanded && Boolean(src) && Boolean(geometry);
  const frameWidth = frameRef.current?.clientWidth ?? 0;
  const frameHeight = frameRef.current?.clientHeight ?? 0;

  // The frame itself becomes a window over a magnified copy of the image.
  // The pixel under the cursor stays under the cursor.
  const zoomStyle: CSSProperties | undefined = active && geometry ? (() => {
    const sampleX = clamp(cursor.x, geometry.left, geometry.left + geometry.width);
    const sampleY = clamp(cursor.y, geometry.top, geometry.top + geometry.height);
    const sampleFracX = geometry.width > 0 ? (sampleX - geometry.left) / geometry.width : 0.5;
    const sampleFracY = geometry.height > 0 ? (sampleY - geometry.top) / geometry.height : 0.5;
    const zoomedWidth = geometry.width * ZOOM;
    const zoomedHeight = geometry.height * ZOOM;
    return {
      backgroundImage: `url("${src}")`,
      backgroundRepeat: "no-repeat",
      backgroundSize: `${zoomedWidth}px ${zoomedHeight}px`,
      backgroundPosition: `${geometry.left + frameWidth / 2 - sampleFracX * zoomedWidth}px ${geometry.top + frameHeight / 2 - sampleFracY * zoomedHeight}px`,
    };
  })() : undefined;

  function handleModalMove(event: MouseEvent<HTMLDivElement>) {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return;
    setModalPoint({
      x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
    });
  }

  const modalStyle = (() => {
    if (!expanded || !geometry) return undefined;
    const stageWidth = stageSize?.width || window.innerWidth - 48;
    const stageHeight = stageSize?.height || window.innerHeight - 80;
    const fit = Math.min(stageWidth / geometry.naturalWidth, stageHeight / geometry.naturalHeight);
    const width = geometry.naturalWidth * fit * modalZoom;
    const height = geometry.naturalHeight * fit * modalZoom;
    return {
      backgroundImage: `url("${src}")`,
      backgroundRepeat: "no-repeat",
      backgroundSize: `${width}px ${height}px`,
      backgroundPosition: `${stageWidth / 2 - modalPoint.x * width}px ${stageHeight / 2 - modalPoint.y * height}px`,
    } satisfies CSSProperties;
  })();

  return (
    <div className="zoom-widget">
      <div
        ref={frameRef}
        className={`image-frame zoom-frame ${active ? "is-zooming" : ""} ${className}`}
        onMouseEnter={(event) => {
          if (src && !expanded) {
            setHovering(true);
            updatePointer(event);
          }
        }}
        onMouseMove={(event) => {
          if (src && !expanded) updatePointer(event);
        }}
        onMouseLeave={() => setHovering(false)}
        onClick={() => {
          if (!src) return;
          setExpanded(true);
          setHovering(false);
          setGeometry(readGeometry());
        }}
        role={src ? "button" : undefined}
        tabIndex={src ? 0 : undefined}
        aria-label={src ? `Open enlarged zoom of ${alt}` : undefined}
        onKeyDown={(event) => {
          if (src && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            setExpanded(true);
            setGeometry(readGeometry());
          }
        }}
      >
        {src ? (
          <>
            <img className="zoom-source-image" src={src} alt={alt} draggable={false} />
            {zoomStyle && <div className="zoom-inplace" style={zoomStyle} aria-hidden="true" />}
            <span className="zoom-hint">{active ? `${ZOOM.toFixed(1)}× · Click to expand` : "Hover to zoom · Click to expand"}</span>
          </>
        ) : children}
      </div>

      {expanded && (
        <div className="zoom-modal" role="dialog" aria-modal="true" aria-label={`Enlarged view of ${alt}`} onClick={() => setExpanded(false)}>
          <button className="zoom-modal-close" aria-label="Close enlarged view" onClick={() => setExpanded(false)}>×</button>
          <div className="zoom-modal-controls" onClick={(event) => event.stopPropagation()}>
            <button onClick={() => setModalZoom((value) => clamp(value - 0.5, 1, 4))} aria-label="Zoom out">−</button>
            <span>{modalZoom.toFixed(1)}×</span>
            <button onClick={() => setModalZoom((value) => clamp(value + 0.5, 1, 4))} aria-label="Zoom in">+</button>
          </div>
          <div
            ref={stageRef}
            className="zoom-modal-stage"
            onMouseMove={handleModalMove}
            onClick={(event) => event.stopPropagation()}
          >
            {modalStyle && <div className="zoom-modal-image" style={modalStyle} />}
          </div>
        </div>
      )}
    </div>
  );
}
