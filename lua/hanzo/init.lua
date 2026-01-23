-- Hanzo AI integration for Neovim
-- Provides enhanced UI, floating windows, and native Lua APIs

local M = {}

-- Configuration
M.config = {
    -- UI settings
    ui = {
        prompt_enabled = true,
        border = "rounded",
        width = 0.8,
        height = 0.4,
    },
    -- Model settings
    model = "claude-sonnet-4-20250514",
    mode = "api",
    -- Keybinds
    set_keymaps = false,
}

-- Setup function
function M.setup(opts)
    M.config = vim.tbl_deep_extend("force", M.config, opts or {})

    -- Sync with Vim globals
    vim.g.hanzo_model = M.config.model
    vim.g.hanzo_mode = M.config.mode

    if M.config.set_keymaps then
        M.setup_keymaps()
    end
end

-- Setup default keymaps
function M.setup_keymaps()
    local keymap = vim.keymap.set
    local opts = { silent = true, noremap = true }

    -- Normal mode
    keymap("n", "<leader>hh", M.prompt, vim.tbl_extend("force", opts, { desc = "Hanzo prompt" }))
    keymap("n", "<leader>hc", "<cmd>HanzoComplete<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo complete" }))
    keymap("n", "<leader>hm", M.model_picker, vim.tbl_extend("force", opts, { desc = "Hanzo model picker" }))

    -- Visual mode
    keymap("v", "<leader>he", "<cmd>HanzoExplain<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo explain" }))
    keymap("v", "<leader>hf", "<cmd>HanzoFix<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo fix" }))
    keymap("v", "<leader>hr", function() M.refactor_prompt() end, vim.tbl_extend("force", opts, { desc = "Hanzo refactor" }))
    keymap("v", "<leader>ht", "<cmd>HanzoTests<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo tests" }))
    keymap("v", "<leader>hd", "<cmd>HanzoDocs<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo docs" }))
    keymap("v", "<leader>hv", "<cmd>HanzoReview<cr>", vim.tbl_extend("force", opts, { desc = "Hanzo review" }))
end

-- Floating window prompt
function M.prompt()
    local width = math.floor(vim.o.columns * M.config.ui.width)
    local height = 1
    local row = math.floor((vim.o.lines - height) / 2)
    local col = math.floor((vim.o.columns - width) / 2)

    local buf = vim.api.nvim_create_buf(false, true)
    local win = vim.api.nvim_open_win(buf, true, {
        relative = "editor",
        width = width,
        height = height,
        row = row,
        col = col,
        style = "minimal",
        border = M.config.ui.border,
        title = " Hanzo AI ",
        title_pos = "center",
    })

    vim.bo[buf].buftype = "prompt"
    vim.fn.prompt_setprompt(buf, "Hanzo> ")

    vim.fn.prompt_setcallback(buf, function(text)
        vim.api.nvim_win_close(win, true)
        if text and text ~= "" then
            vim.fn["hanzo#Chat"](text)
        end
    end)

    vim.cmd("startinsert")

    -- Close on escape
    vim.keymap.set("n", "<Esc>", function()
        vim.api.nvim_win_close(win, true)
    end, { buffer = buf })
end

-- Refactor with prompt
function M.refactor_prompt()
    vim.ui.input({ prompt = "Refactor instruction: " }, function(input)
        if input and input ~= "" then
            vim.fn["hanzo#Refactor"](input)
        end
    end)
end

-- Model picker using vim.ui.select
function M.model_picker()
    local models = {
        { name = "claude-sonnet-4-20250514", desc = "Claude Sonnet 4 (Latest)" },
        { name = "claude-opus-4-20250514", desc = "Claude Opus 4" },
        { name = "claude-3-5-sonnet-20241022", desc = "Claude 3.5 Sonnet" },
        { name = "gpt-4-turbo", desc = "GPT-4 Turbo" },
        { name = "gpt-4o", desc = "GPT-4 Omni" },
        { name = "gemini-1.5-pro", desc = "Gemini 1.5 Pro" },
        { name = "ollama:llama3.2", desc = "Llama 3.2 (Local)" },
        { name = "ollama:codellama", desc = "Code Llama (Local)" },
    }

    vim.ui.select(models, {
        prompt = "Select model:",
        format_item = function(item)
            return item.desc
        end,
    }, function(choice)
        if choice then
            vim.fn["hanzo#SetModel"](choice.name)
        end
    end)
end

-- Mode picker
function M.mode_picker()
    vim.ui.select({ "api", "mcp", "ollama" }, {
        prompt = "Select mode:",
    }, function(choice)
        if choice then
            vim.fn["hanzo#SetMode"](choice)
        end
    end)
end

-- Get current status
function M.status()
    return {
        model = vim.g.hanzo_model or M.config.model,
        mode = vim.g.hanzo_mode or M.config.mode,
        bridge = vim.fn.exists("*hanzo#BridgeStatus") == 1 and vim.fn["hanzo#BridgeStatus"]() or "unknown",
    }
end

-- Animated sign for processing (like Neural)
local sign_timer = nil
local sign_line = 0
local sign_frames = { "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏" }
local sign_frame = 1

function M.start_animated_sign(line)
    sign_line = line
    sign_frame = 1

    -- Define sign
    vim.fn.sign_define("HanzoWorking", { text = sign_frames[1], texthl = "Question" })
    vim.fn.sign_place(1, "hanzo", "HanzoWorking", vim.fn.bufnr("%"), { lnum = line })

    -- Start animation
    sign_timer = vim.loop.new_timer()
    sign_timer:start(100, 100, vim.schedule_wrap(function()
        sign_frame = (sign_frame % #sign_frames) + 1
        vim.fn.sign_define("HanzoWorking", { text = sign_frames[sign_frame], texthl = "Question" })
    end))
end

function M.stop_animated_sign(line)
    if sign_timer then
        sign_timer:stop()
        sign_timer:close()
        sign_timer = nil
    end
    vim.fn.sign_unplace("hanzo", { buffer = vim.fn.bufnr("%") })
end

return M
