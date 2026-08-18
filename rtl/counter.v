// =============================================================================
// counter.v — Sample 8-bit Up-Counter (SHIPP RTL Proof-of-Concept Module)
// =============================================================================
// A minimal synchronous 8-bit up-counter with synchronous active-high reset
// and a clock-enable input.
//
// Ports
// -----
//   clk    : input  -- system clock (rising-edge triggered)
//   rst    : input  -- synchronous active-high reset (drives count to 0)
//   en     : input  -- clock enable (count increments only when en=1)
//   count  : output -- current counter value [7:0]
//
// This module is intentionally small and self-contained so that the SHIPP
// watermarking proof-of-concept (rtl_embed.py) has a clean, readable host
// module to work with.  It does NOT include the watermark -- the watermarked
// version is written to outputs/counter_watermarked.v by rtl_embed.py.
// =============================================================================

module counter (
    input  wire       clk,
    input  wire       rst,
    input  wire       en,
    output reg  [7:0] count
);

    always @(posedge clk) begin
        if (rst)
            count <= 8'b0;
        else if (en)
            count <= count + 8'b1;
    end

endmodule
