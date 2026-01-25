
local ScreenGui = Instance.new("ScreenGui")
local MainFrame = Instance.new("Frame")
local TitleBar = Instance.new("Frame")
local Title = Instance.new("TextLabel")
local CloseButton = Instance.new("TextButton")
local MinimizeButton = Instance.new("TextButton")
local ScrollFrame = Instance.new("ScrollingFrame")
local UIListLayout = Instance.new("UIListLayout")
local UIPadding = Instance.new("UIPadding")

local CountdownGui = Instance.new("ScreenGui")
local CountdownFrame = Instance.new("Frame")
local CountdownLabel = Instance.new("TextLabel")

_G.SelectedPackage = nil
_G.Countdown = 0

local Packages = {
    {
        id = "3K",
        name = "Random Blox Fruits 3K",
        price = "3,000 VNĐ",
        info = {
            "Level 700+",
            "Full melee v1 (có thể full chiêu)",
            "1-2 trái legendary",
            "Trên 2M tiền, 5,000 fragments",
            "Account có thể xịn hơn do random"
        }
    },
    {
        id = "10K",
        name = "Random Blox Fruits 10K",
        price = "10,000 VNĐ",
        info = {
            "Level 1100+",
            "Có 1 tộc v3",
            "1 trái đang dùng full chiêu thức tỉnh",
            "Có Superhuman full chiêu",
            "2-3 trái legendary hoặc mythical",
            "Trên 4M tiền, 5,000 fragments",
            "Account có thể xịn hơn do random"
        }
    },
    {
        id = "20K",
        name = "Random Blox Fruits 20K",
        price = "20,000 VNĐ",
        info = {
            "Level 1500+",
            "Có tộc v3",
            "1-2 kiếm legendary",
            "Full melee v1, gần full melee v2",
            "Trên 6M tiền, 5,000 fragments",
            "Account có thể xịn hơn do random"
        }
    },
    {
        id = "50K",
        name = "Random Blox Fruits 50K",
        price = "50,000 VNĐ",
        info = {
            "Level 2200+",
            "Có Godhuman",
            "Có thể có Soul Guitar, CDK, TTK",
            "1-2 trái mythical",
            "Trên 2 trái thức tỉnh",
            "1-2 tộc v3 hoặc v4",
            "Trên 8M tiền, 8,000 fragments",
            "Account có thể xịn hơn do random"
        }
    },
    {
        id = "CUSTOM",
        name = "Blox Fruits Tự Chọn",
        price = "Trên 100,000 VNĐ",
        info = {
            "Level 2500+",
            "Yêu cầu 1-2 kiếm đỏ",
            "Có 1-2 trái đỏ",
            "Nhiều items, nhiều trái legendary",
            "Có 1 tộc v4",
            "Súng gần như full chiêu",
            "Có thể có súng rồng hoặc tộc rồng",
            "Nhiều trái thức tỉnh",
            "Trên 10M tiền, 10,000 fragments",
            "Full haki, có thể có haki v2 và màu"
        }
    }
}

ScreenGui.Name = "KaitunGUI"
ScreenGui.Parent = game.CoreGui
ScreenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

MainFrame.Name = "MainFrame"
MainFrame.Parent = ScreenGui
MainFrame.BackgroundColor3 = Color3.fromRGB(25, 25, 25)
MainFrame.BorderSizePixel = 0
MainFrame.Position = UDim2.new(0.5, -300, 0.5, -250)
MainFrame.Size = UDim2.new(0, 600, 0, 500)
MainFrame.Active = true
MainFrame.Draggable = true

local MainCorner = Instance.new("UICorner")
MainCorner.CornerRadius = UDim.new(0, 8)
MainCorner.Parent = MainFrame

TitleBar.Name = "TitleBar"
TitleBar.Parent = MainFrame
TitleBar.BackgroundColor3 = Color3.fromRGB(35, 35, 35)
TitleBar.BorderSizePixel = 0
TitleBar.Size = UDim2.new(1, 0, 0, 40)

local TitleCorner = Instance.new("UICorner")
TitleCorner.CornerRadius = UDim.new(0, 8)
TitleCorner.Parent = TitleBar

Title.Name = "Title"
Title.Parent = TitleBar
Title.BackgroundTransparency = 1
Title.Position = UDim2.new(0, 15, 0, 0)
Title.Size = UDim2.new(0.7, 0, 1, 0)
Title.Font = Enum.Font.GothamBold
Title.Text = "Hệ Thống Kaitun Blox Fruits"
Title.TextColor3 = Color3.fromRGB(255, 255, 255)
Title.TextSize = 16
Title.TextXAlignment = Enum.TextXAlignment.Left

CloseButton.Name = "CloseButton"
CloseButton.Parent = TitleBar
CloseButton.BackgroundColor3 = Color3.fromRGB(255, 50, 50)
CloseButton.BorderSizePixel = 0
CloseButton.Position = UDim2.new(1, -35, 0.5, -12)
CloseButton.Size = UDim2.new(0, 24, 0, 24)
CloseButton.Font = Enum.Font.GothamBold
CloseButton.Text = "X"
CloseButton.TextColor3 = Color3.fromRGB(255, 255, 255)
CloseButton.TextSize = 14

local CloseCorner = Instance.new("UICorner")
CloseCorner.CornerRadius = UDim.new(0, 4)
CloseCorner.Parent = CloseButton

MinimizeButton.Name = "MinimizeButton"
MinimizeButton.Parent = TitleBar
MinimizeButton.BackgroundColor3 = Color3.fromRGB(100, 100, 100)
MinimizeButton.BorderSizePixel = 0
MinimizeButton.Position = UDim2.new(1, -65, 0.5, -12)
MinimizeButton.Size = UDim2.new(0, 24, 0, 24)
MinimizeButton.Font = Enum.Font.GothamBold
MinimizeButton.Text = "_"
MinimizeButton.TextColor3 = Color3.fromRGB(255, 255, 255)
MinimizeButton.TextSize = 14

local MinCorner = Instance.new("UICorner")
MinCorner.CornerRadius = UDim.new(0, 4)
MinCorner.Parent = MinimizeButton

ScrollFrame.Name = "ScrollFrame"
ScrollFrame.Parent = MainFrame
ScrollFrame.BackgroundColor3 = Color3.fromRGB(30, 30, 30)
ScrollFrame.BorderSizePixel = 0
ScrollFrame.Position = UDim2.new(0, 10, 0, 50)
ScrollFrame.Size = UDim2.new(1, -20, 1, -60)
ScrollFrame.ScrollBarThickness = 6
ScrollFrame.ScrollBarImageColor3 = Color3.fromRGB(80, 80, 80)
ScrollFrame.CanvasSize = UDim2.new(0, 0, 0, 0)

local ScrollCorner = Instance.new("UICorner")
ScrollCorner.CornerRadius = UDim.new(0, 6)
ScrollCorner.Parent = ScrollFrame

UIListLayout.Parent = ScrollFrame
UIListLayout.SortOrder = Enum.SortOrder.LayoutOrder
UIListLayout.Padding = UDim.new(0, 10)

UIPadding.Parent = ScrollFrame
UIPadding.PaddingTop = UDim.new(0, 10)
UIPadding.PaddingBottom = UDim.new(0, 10)
UIPadding.PaddingLeft = UDim.new(0, 10)
UIPadding.PaddingRight = UDim.new(0, 10)

CountdownGui.Name = "CountdownNotify"
CountdownGui.Parent = game.CoreGui
CountdownGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

CountdownFrame.Name = "CountdownFrame"
CountdownFrame.Parent = CountdownGui
CountdownFrame.BackgroundColor3 = Color3.fromRGB(35, 35, 35)
CountdownFrame.BorderSizePixel = 0
CountdownFrame.Position = UDim2.new(0.5, -150, 0, 20)
CountdownFrame.Size = UDim2.new(0, 300, 0, 50)
CountdownFrame.Visible = false

local CountdownCorner = Instance.new("UICorner")
CountdownCorner.CornerRadius = UDim.new(0, 8)
CountdownCorner.Parent = CountdownFrame

CountdownLabel.Name = "CountdownLabel"
CountdownLabel.Parent = CountdownFrame
CountdownLabel.BackgroundTransparency = 1
CountdownLabel.Size = UDim2.new(1, 0, 1, 0)
CountdownLabel.Font = Enum.Font.GothamBold
CountdownLabel.Text = ""
CountdownLabel.TextColor3 = Color3.fromRGB(255, 255, 255)
CountdownLabel.TextSize = 14

local function showCountdown(packageName)
    CountdownFrame.Visible = true
    _G.Countdown = 5
    
    spawn(function()
        while _G.Countdown > 0 do
            CountdownLabel.Text = "Bắt đầu sau " .. _G.Countdown .. " giây..."
            CountdownLabel.TextColor3 = Color3.fromRGB(255, 200, 100)
            wait(1)
            _G.Countdown = _G.Countdown - 1
        end
        
        CountdownLabel.Text = "Đang tải Kaitun Script..."
        CountdownLabel.TextColor3 = Color3.fromRGB(100, 200, 255)
        wait(0.5)
        
        getgenv().Deleted_Ui = true
        loadstring(game:HttpGet("https://raw.githubusercontent.com/Huyyhere/SwitchHubKaitun/refs/heads/main/SwitchKaitun.lua"))()
        
        CountdownLabel.Text = "Đã load thành công!"
        CountdownLabel.TextColor3 = Color3.fromRGB(100, 255, 100)
        
        game.StarterGui:SetCore("SendNotification", {
            Title = "Kaitun System";
            Text = "Đã load Random Blox Fruits " .. packageName;
            Duration = 5;
        })
        
        wait(2)
        CountdownFrame.Visible = false
    end)
end

local function createPackageButton(package)
    local Container = Instance.new("Frame")
    local Button = Instance.new("TextButton")
    local ButtonCorner = Instance.new("UICorner")
    local NameLabel = Instance.new("TextLabel")
    local PriceLabel = Instance.new("TextLabel")
    local InfoContainer = Instance.new("Frame")
    local InfoLayout = Instance.new("UIListLayout")
    local LoadButton = Instance.new("TextButton")
    local LoadCorner = Instance.new("UICorner")
    
    Container.Name = package.id .. "Container"
    Container.Parent = ScrollFrame
    Container.BackgroundTransparency = 1
    Container.Size = UDim2.new(1, -20, 0, 50)
    
    Button.Name = package.id
    Button.Parent = Container
    Button.BackgroundColor3 = Color3.fromRGB(45, 45, 45)
    Button.BorderSizePixel = 0
    Button.Size = UDim2.new(1, 0, 1, 0)
    Button.AutoButtonColor = false
    Button.Text = ""
    
    ButtonCorner.CornerRadius = UDim.new(0, 6)
    ButtonCorner.Parent = Button
    
    NameLabel.Name = "NameLabel"
    NameLabel.Parent = Button
    NameLabel.BackgroundTransparency = 1
    NameLabel.Position = UDim2.new(0, 15, 0, 5)
    NameLabel.Size = UDim2.new(0.5, 0, 0, 20)
    NameLabel.Font = Enum.Font.GothamBold
    NameLabel.Text = package.name
    NameLabel.TextColor3 = Color3.fromRGB(255, 255, 255)
    NameLabel.TextSize = 15
    NameLabel.TextXAlignment = Enum.TextXAlignment.Left
    
    PriceLabel.Name = "PriceLabel"
    PriceLabel.Parent = Button
    PriceLabel.BackgroundTransparency = 1
    PriceLabel.Position = UDim2.new(0, 15, 0, 25)
    PriceLabel.Size = UDim2.new(0.5, 0, 0, 20)
    PriceLabel.Font = Enum.Font.Gotham
    PriceLabel.Text = "Giá: " .. package.price
    PriceLabel.TextColor3 = Color3.fromRGB(150, 220, 150)
    PriceLabel.TextSize = 13
    PriceLabel.TextXAlignment = Enum.TextXAlignment.Left
    
    InfoContainer.Name = "InfoContainer"
    InfoContainer.Parent = Container
    InfoContainer.BackgroundTransparency = 1
    InfoContainer.Position = UDim2.new(0, 0, 0, 55)
    InfoContainer.Size = UDim2.new(1, 0, 0, 0)
    InfoContainer.Visible = false
    
    InfoLayout.Parent = InfoContainer
    InfoLayout.SortOrder = Enum.SortOrder.LayoutOrder
    InfoLayout.Padding = UDim.new(0, 3)
    
    for i, line in ipairs(package.info) do
        local InfoLabel = Instance.new("TextLabel")
        InfoLabel.Parent = InfoContainer
        InfoLabel.BackgroundTransparency = 1
        InfoLabel.Size = UDim2.new(1, 0, 0, 18)
        InfoLabel.Font = Enum.Font.Gotham
        InfoLabel.Text = "  " .. line
        InfoLabel.TextColor3 = Color3.fromRGB(200, 200, 200)
        InfoLabel.TextSize = 12
        InfoLabel.TextXAlignment = Enum.TextXAlignment.Left
    end
    
    LoadButton.Name = "LoadButton"
    LoadButton.Parent = InfoContainer
    LoadButton.BackgroundColor3 = Color3.fromRGB(50, 150, 50)
    LoadButton.BorderSizePixel = 0
    LoadButton.Position = UDim2.new(0, 0, 1, 5)
    LoadButton.Size = UDim2.new(1, 0, 0, 35)
    LoadButton.Font = Enum.Font.GothamBold
    LoadButton.Text = "Load Script"
    LoadButton.TextColor3 = Color3.fromRGB(255, 255, 255)
    LoadButton.TextSize = 14
    
    LoadCorner.CornerRadius = UDim.new(0, 6)
    LoadCorner.Parent = LoadButton
    
    local expanded = false
    Button.MouseButton1Click:Connect(function()
        if not expanded then
            expanded = true
            InfoContainer.Visible = true
            local infoHeight = (#package.info * 21) + 45
            Container.Size = UDim2.new(1, -20, 0, 50 + infoHeight)
            InfoContainer.Size = UDim2.new(1, 0, 0, infoHeight)
            Button.BackgroundColor3 = Color3.fromRGB(55, 55, 55)
            
            game.StarterGui:SetCore("SendNotification", {
                Title = package.name;
                Text = "Nhấn Load Script để bắt đầu";
                Duration = 3;
            })
        else
            expanded = false
            InfoContainer.Visible = false
            Container.Size = UDim2.new(1, -20, 0, 50)
            Button.BackgroundColor3 = Color3.fromRGB(45, 45, 45)
        end
    end)
    
    LoadButton.MouseButton1Click:Connect(function()
        _G.SelectedPackage = package.id
        showCountdown(package.name)
    end)
    
    LoadButton.MouseEnter:Connect(function()
        LoadButton.BackgroundColor3 = Color3.fromRGB(60, 180, 60)
    end)
    
    LoadButton.MouseLeave:Connect(function()
        LoadButton.BackgroundColor3 = Color3.fromRGB(50, 150, 50)
    end)
    
    Button.MouseEnter:Connect(function()
        if not expanded then
            Button.BackgroundColor3 = Color3.fromRGB(55, 55, 55)
        end
    end)
    
    Button.MouseLeave:Connect(function()
        if not expanded then
            Button.BackgroundColor3 = Color3.fromRGB(45, 45, 45)
        end
    end)
end

for _, package in ipairs(Packages) do
    createPackageButton(package)
end

local InfoLabel = Instance.new("TextLabel")
InfoLabel.Parent = ScrollFrame
InfoLabel.BackgroundColor3 = Color3.fromRGB(40, 40, 40)
InfoLabel.BorderSizePixel = 0
InfoLabel.Size = UDim2.new(1, -20, 0, 80)
InfoLabel.Font = Enum.Font.Gotham
InfoLabel.Text = "Hướng dẫn: Nhấn vào Random Blox Fruits để xem chi tiết\nNhấn Load Script để chọn và load\n\nLưu ý: Tất cả account đều có full haki\nAccount xịn có thể có haki v2 và màu"
InfoLabel.TextColor3 = Color3.fromRGB(180, 180, 180)
InfoLabel.TextSize = 12
InfoLabel.TextWrapped = true

local InfoCorner = Instance.new("UICorner")
InfoCorner.CornerRadius = UDim.new(0, 6)
InfoCorner.Parent = InfoLabel

UIListLayout:GetPropertyChangedSignal("AbsoluteContentSize"):Connect(function()
    ScrollFrame.CanvasSize = UDim2.new(0, 0, 0, UIListLayout.AbsoluteContentSize.Y + 30)
end)

CloseButton.MouseButton1Click:Connect(function()
    ScreenGui:Destroy()
    CountdownGui:Destroy()
end)

local minimized = false
MinimizeButton.MouseButton1Click:Connect(function()
    minimized = not minimized
    if minimized then
        MainFrame.Size = UDim2.new(0, 600, 0, 40)
        ScrollFrame.Visible = false
    else
        MainFrame.Size = UDim2.new(0, 600, 0, 500)
        ScrollFrame.Visible = true
    end
end)
